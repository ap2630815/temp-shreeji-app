"""Truck trips: loading from commencings, the bilty (weights, rate, broker) and what follows from it."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi_csrf_protect import CsrfProtect
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.api.formkit import GENERIC_ERROR, YEAR_LOCKED, form_context, lock, normalize_fields, read_form, today
from app.api.masters_config import F, run_validation
from app.core.db import get_db
from app.core.templating import render, render_with_csrf
from app.models import (
    Bilty, BusinessYear, Broker, Commencing, Grain, Industry, LabourGroup, Transporter, TruckLoadLine, TruckTrip, Truck, User,
)
from app.models.sales import _ceil_div, freight_amount
from app.services import audit
from app.services.locks import advisory_lock
from app.services.payables import paid_for
from app.services.receivables import received_map
from app.services.stock import stock_by_commencing
from app.services.years import YearLockedError, assert_year_open, business_year_of

router = APIRouter(prefix="/trips")

INT_MAX = 100_000_000
WEIGHT_MAX = 200_000  # kg; no truck carries more
SHORT_WARN_PCT = 1  # highlight a weight shortage at or above this percentage


def _int(ge=0, gt=None, le=INT_MAX):
    return Annotated[int, Field(ge=ge, le=le)] if gt is None else Annotated[int, Field(gt=gt, le=le)]


# ================================================================== trip form

class TripIn(BaseModel):
    trip_date: date
    truck_id: int
    transport_id: int
    labour_group_id: int
    industry_id: int
    grain_id: int
    rent_per_ton: _int() | None = None
    rent_per_bag: _int() | None = None
    advance_amount: _int() | None = None
    other_deduction: _int() | None = None
    description: str | None = None


ZERO_FIELDS = ("rent_per_ton", "rent_per_bag", "advance_amount", "other_deduction")


async def _options(db: AsyncSession, model, order):
    return list((await db.scalars(select(model).order_by(order))).all())


async def trip_fields(db: AsyncSession) -> list[F]:
    trucks, transports = await _options(db, Truck, Truck.truck_number), await _options(db, Transporter, Transporter.pet_name)
    groups, industries, grains = await _options(db, LabourGroup, LabourGroup.group_name), await _options(db, Industry, Industry.name), await _options(db, Grain, Grain.name)
    return [
        F("trip_date", "Date", "તારીખ", kind="date", required=True),
        F("truck_id", "Truck", "ટ્રક", kind="select", required=True, options=tuple((str(t.id), f"{t.truck_number} — {t.driver_name}") for t in trucks)),
        F("transport_id", "Transport", "ટ્રાન્સપોર્ટ", kind="select", required=True, options=tuple((str(t.id), f"{t.pet_name} — {t.location}") for t in transports)),
        F("labour_group_id", "Loading labour", "લોડિંગ મજૂર", kind="select", required=True, options=tuple((str(g.id), f"{g.group_name} — {g.name}") for g in groups)),
        F("industry_id", "Industry (unloading at)", "ઉદ્યોગ (ખાલી થશે)", kind="select", required=True, options=tuple((str(i.id), f"{i.name} — {i.location}") for i in industries)),
        F("grain_id", "Grain (one per trip)", "અનાજ (એક ટ્રીપમાં એક)", kind="select", required=True, options=tuple((str(g.id), f"{g.name} / {g.name_gu or ''}") for g in grains)),
        F("rent_per_ton", "Rent per ton (₹)", "ટન દીઠ ભાડું (₹)", kind="int",
          help=("Freight = the larger of rent/ton × tons and rent/bag × bags", "ભાડું = ટન ભાડું × ટન અને બેગ ભાડું × બેગ માંથી મોટું")),
        F("rent_per_bag", "Rent per bag (₹)", "બેગ દીઠ ભાડું (₹)", kind="int"),
        F("advance_amount", "Advance given to driver (₹)", "ડ્રાઇવરને આપેલ એડવાન્સ (₹)", kind="int"),
        F("other_deduction", "Other deduction (₹)", "અન્ય કપાત (₹)", kind="int"),
        F("description", "Description", "વર્ણન", kind="textarea"),
    ]


def trip_values(t: TruckTrip) -> dict:
    return dict(
        trip_date=t.trip_date.isoformat(), truck_id=str(t.truck_id), transport_id=str(t.transport_id), labour_group_id=str(t.labour_group_id),
        industry_id=str(t.industry_id), grain_id=str(t.grain_id), rent_per_ton=str(t.rent_per_ton), rent_per_bag=str(t.rent_per_bag),
        advance_amount=str(t.advance_amount), other_deduction=str(t.other_deduction), description=t.description or "",
    )


def trip_snapshot(t: TruckTrip) -> dict:
    return dict(
        trip_date=t.trip_date, truck_id=t.truck_id, transport_id=t.transport_id, labour_group_id=t.labour_group_id, industry_id=t.industry_id,
        grain_id=t.grain_id, rent_per_ton=t.rent_per_ton, rent_per_bag=t.rent_per_bag, advance_amount=t.advance_amount,
        other_deduction=t.other_deduction, description=t.description,
    )


# ================================================================== bilty form

class BiltyIn(BaseModel):
    bill_number: _int(gt=0)
    bilty_date: date
    broker_id: int
    grain_rate: _int(gt=0)
    rate_unit_kg: _int(gt=0, le=1000)
    rate_change: _int() | None = None
    brokerage_amount: _int() | None = None
    merchant_total_weight: _int(gt=0, le=WEIGHT_MAX)
    merchant_tare_weight: _int(le=WEIGHT_MAX)
    industry_total_weight: _int(gt=0, le=WEIGHT_MAX) | None = None
    industry_tare_weight: _int(le=WEIGHT_MAX) | None = None
    description: str | None = None


async def bilty_fields(db: AsyncSession) -> list[F]:
    brokers = await _options(db, Broker, Broker.name)
    kg = ("kg", "કિલો")
    return [
        F("bill_number", "Bill number", "બિલ નંબર", kind="int", required=True, help=("Unique within the business year", "વ્યવસાય વર્ષમાં અનન્ય")),
        F("bilty_date", "Bilty date", "બિલ્ટી તારીખ", kind="date", required=True),
        F("broker_id", "Broker", "દલાલ", kind="select", required=True, options=tuple((str(b.id), f"{b.name} — ₹{b.brokerage_per_truck}/truck") for b in brokers)),
        F("brokerage_amount", "Brokerage for this truck (₹)", "આ ટ્રકની દલાલી (₹)", kind="int",
          help=("Leave blank to use the broker's standard brokerage", "ખાલી રાખો તો દલાલની નક્કી દલાલી લેવાશે")),
        F("grain_rate", "Sale rate (₹)", "વેચાણ ભાવ (₹)", kind="int", required=True),
        F("rate_unit_kg", "Rate is per (kg)", "ભાવ કેટલા કિલો દીઠ", kind="int", required=True, help=("e.g. 20 or 100", "દા.ત. 20 અથવા 100")),
        F("rate_change", "Rate reduction after delivery (₹)", "ડિલિવરી પછી ભાવ ઘટાડો (₹)", kind="int"),
        F("merchant_total_weight", f"Our weighbridge: loaded truck ({kg[0]})", f"આપણો કાંટો: ભરેલી ટ્રક ({kg[1]})", kind="int", required=True),
        F("merchant_tare_weight", f"Our weighbridge: empty truck ({kg[0]})", f"આપણો કાંટો: ખાલી ટ્રક ({kg[1]})", kind="int", required=True),
        F("industry_total_weight", f"Industry: loaded truck ({kg[0]})", f"કારખાનું: ભરેલી ટ્રક ({kg[1]})", kind="int",
          help=("Fill after unloading; the receivable is calculated from this", "ખાલી થયા પછી ભરો; લેણાં આના પરથી ગણાય છે")),
        F("industry_tare_weight", f"Industry: empty truck ({kg[0]})", f"કારખાનું: ખાલી ટ્રક ({kg[1]})", kind="int"),
        F("description", "Description (mismatch, bags unloaded…)", "વર્ણન (તફાવત, ઉતારેલી બેગ…)", kind="textarea"),
    ]


def bilty_values(b: Bilty) -> dict:
    n = lambda v: "" if v is None else str(v)  # noqa: E731
    return dict(
        bill_number=str(b.bill_number), bilty_date=b.bilty_date.isoformat(), broker_id=str(b.broker_id), brokerage_amount=str(b.brokerage_amount),
        grain_rate=str(b.grain_rate), rate_unit_kg=str(b.rate_unit_kg), rate_change=str(b.rate_change),
        merchant_total_weight=str(b.merchant_total_weight), merchant_tare_weight=str(b.merchant_tare_weight),
        industry_total_weight=n(b.industry_total_weight), industry_tare_weight=n(b.industry_tare_weight), description=b.description or "",
    )


def bilty_snapshot(b: Bilty) -> dict:
    return dict(
        bill_number=b.bill_number, bilty_date=b.bilty_date, broker_id=b.broker_id, brokerage_amount=b.brokerage_amount, grain_rate=b.grain_rate,
        rate_unit_kg=b.rate_unit_kg, rate_change=b.rate_change, merchant_total_weight=b.merchant_total_weight,
        merchant_tare_weight=b.merchant_tare_weight, industry_total_weight=b.industry_total_weight,
        industry_tare_weight=b.industry_tare_weight, description=b.description,
    )


# ================================================================== load line form

class LineIn(BaseModel):
    commencing_id: int
    bags: _int(gt=0)


async def line_fields(db: AsyncSession, trip: TruckTrip) -> list[F]:
    commencings = list((await db.scalars(select(Commencing).where(Commencing.grain_id == trip.grain_id).order_by(Commencing.commencing_date.desc(), Commencing.id.desc()))).all())
    stock = await stock_by_commencing(db, [c.id for c in commencings])
    options = tuple(
        (str(c.id), f"{c.village} · {c.commencing_date} — {stock[c.id].available} bags available")
        for c in commencings if c.id in stock and stock[c.id].available > 0
    )
    return [
        F("commencing_id", "Load from (village / commencing)", "ક્યાંથી ભર્યું (ગામ / કમેન્સિંગ)", kind="select", required=True, options=options),
        F("bags", "Bags loaded", "ભરેલી બેગ", kind="int", required=True),
    ]


# ================================================================== helpers

async def _get_trip(db: AsyncSession, trip_id: int) -> TruckTrip:
    trip = await db.get(TruckTrip, trip_id)
    if trip is None:
        raise HTTPException(404)
    return trip


def _final(freight: int, advance: int, deduction: int) -> int:
    return max(freight - advance - deduction, 0)


def _below_paid(paid: int, new_amount: int, what: tuple[str, str]) -> tuple[str, str] | None:
    if new_amount < paid:
        return (f"₹{paid} is already paid as {what[0]}; this change would take it below that", f"{what[1]} તરીકે ₹{paid} ચૂકવાઈ ગયા છે; આ ફેરફારથી તે ઓછું થશે")
    return None


async def _years_with_trips(db: AsyncSession) -> list[str]:
    rows = (await db.scalars(select(TruckTrip.business_year).distinct())).all()
    return sorted({business_year_of(today()), *rows}, reverse=True)


# ================================================================== list

@router.get("", response_class=HTMLResponse)
async def list_page(
    request: Request, year: str = "", user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    years = await _years_with_trips(db)
    year = year if year in years else business_year_of(today())
    trips = list((await db.scalars(select(TruckTrip).where(TruckTrip.business_year == year).order_by(TruckTrip.trip_date.desc(), TruckTrip.id.desc()))).unique().all())
    locked = await db.get(BusinessYear, year)
    return render_with_csrf(request, csrf, "trip_list.html", user=user, trips=trips, year=year, years=years,
                            year_locked=bool(locked and locked.is_locked), warn_pct=SHORT_WARN_PCT)


# ================================================================== trip create / edit

@router.get("/new", response_class=HTMLResponse)
async def new_page(request: Request, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    ctx = form_context(fields=await trip_fields(db), values=dict(trip_date=today().isoformat(), rent_per_ton="0", rent_per_bag="0", advance_amount="0", other_deduction="0"),
                       errors={}, action="/trips", heading=("New truck trip", "નવી ટ્રક ટ્રીપ"), back_url="/trips")
    return render_with_csrf(request, csrf, "master_form_page.html", user=user, **ctx)


@router.get("/{trip_id}/edit", response_class=HTMLResponse)
async def edit_page(request: Request, trip_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    trip = await _get_trip(db, trip_id)
    fields = lock(await trip_fields(db), {"grain_id"} if trip.load_lines else set())
    ctx = form_context(fields=fields, values=trip_values(trip), errors={}, action=f"/trips/{trip.id}",
                       heading=(f"Edit trip: {trip.truck.truck_number}", f"ટ્રીપ સુધારો: {trip.truck.truck_number}"), back_url=f"/trips/{trip.id}")
    return render_with_csrf(request, csrf, "master_form_page.html", user=user, **ctx)


@router.post("", response_class=HTMLResponse)
async def create_trip(request: Request, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    await csrf.validate_csrf(request)
    return await _save_trip(request, None, user, db)


@router.post("/{trip_id}", response_class=HTMLResponse)
async def update_trip(request: Request, trip_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    await csrf.validate_csrf(request)
    return await _save_trip(request, await _get_trip(db, trip_id), user, db)


async def _save_trip(request: Request, trip: TruckTrip | None, user: User, db: AsyncSession):
    trip_id = trip.id if trip else None
    fields = await trip_fields(db)
    raw = await read_form(request)
    if trip is not None and trip.load_lines:
        fields = lock(fields, {"grain_id"})
        raw["grain_id"] = str(trip.grain_id)  # a trip with loaded bags keeps its grain
    action = f"/trips/{trip_id}" if trip_id else "/trips"
    heading = ("Edit trip", "ટ્રીપ સુધારો") if trip else ("New truck trip", "નવી ટ્રક ટ્રીપ")

    def rerender(errs):
        return render(request, "partials/master_form.html", **form_context(
            fields=fields, values=raw, errors=errs, action=action, heading=heading, back_url=f"/trips/{trip_id}" if trip_id else "/trips"))

    clean, errors = run_validation(TripIn, fields, normalize_fields(fields, raw))
    if errors:
        return rerender(errors)
    for name in ZERO_FIELDS:
        clean[name] = clean[name] or 0
    for name, model in (("truck_id", Truck), ("transport_id", Transporter), ("labour_group_id", LabourGroup), ("industry_id", Industry), ("grain_id", Grain)):
        if await db.get(model, clean[name]) is None:
            return rerender({name: ("Unknown value", "અજ્ઞાત કિંમત")})
    try:
        clean["business_year"] = await assert_year_open(db, clean["trip_date"])
        if trip is not None:
            await assert_year_open(db, trip.trip_date)
    except YearLockedError as exc:
        return rerender({"trip_date": YEAR_LOCKED(exc.label)})

    before = None
    if trip is not None:
        freight = freight_amount(trip.freight_weight_kg, trip.bags, clean["rent_per_ton"], clean["rent_per_bag"])
        problem = _below_paid(await paid_for(db, "truck_trip", trip.id), _final(freight, clean["advance_amount"], clean["other_deduction"]), ("freight", "ભાડા"))
        if problem:
            return rerender({"rent_per_ton": problem})
        before = trip_snapshot(trip)
        for name, value in clean.items():
            setattr(trip, name, value)
    else:
        trip = TruckTrip(created_by=user.id, **clean)
        db.add(trip)
    await db.flush()
    audit.log(db, user, "update" if before else "create", "truck_trips", trip.id, audit.diff(before, trip_snapshot(trip)))
    new_id = trip.id
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return rerender({"trip_date": GENERIC_ERROR})
    return Response(status_code=204, headers={"HX-Redirect": f"/trips/{new_id}"})


# ================================================================== detail

@router.get("/{trip_id}", response_class=HTMLResponse)
async def detail_page(request: Request, trip_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    trip = await _get_trip(db, trip_id)
    bilty = trip.bilty
    line_form = form_context(fields=await line_fields(db, trip), values={}, errors={}, action=f"/trips/{trip.id}/lines", heading=("Add load", "લોડ ઉમેરો"), back_url=f"/trips/{trip.id}")
    ctx = dict(
        trip=trip, bilty=bilty, line_form=line_form, warn_pct=SHORT_WARN_PCT,
        freight_paid=await paid_for(db, "truck_trip", trip.id),
        brokerage_paid=await paid_for(db, "bilty_brokerage", bilty.id) if bilty else 0,
        received=(await received_map(db, [bilty.id])).get(bilty.id, 0) if bilty else 0,
    )
    return render_with_csrf(request, csrf, "trip_detail.html", user=user, **ctx)


# ================================================================== load lines

@router.post("/{trip_id}/lines", response_class=HTMLResponse)
async def add_line(request: Request, trip_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    await csrf.validate_csrf(request)
    trip = await _get_trip(db, trip_id)
    fields = await line_fields(db, trip)
    raw = await read_form(request)
    form = lambda errs: render(request, "partials/master_form.html", **form_context(  # noqa: E731
        fields=fields, values=raw, errors=errs, action=f"/trips/{trip_id}/lines", heading=("Add load", "લોડ ઉમેરો"), back_url=f"/trips/{trip_id}"))
    clean, errors = run_validation(LineIn, fields, normalize_fields(fields, raw))
    if errors:
        return form(errors)
    try:
        await assert_year_open(db, trip.trip_date)
    except YearLockedError as exc:
        return form({"bags": YEAR_LOCKED(exc.label)})
    commencing = await db.get(Commencing, clean["commencing_id"])
    if commencing is None or commencing.grain_id != trip.grain_id:
        return form({"commencing_id": ("Pick a village with the same grain as this trip", "આ ટ્રીપના અનાજવાળું ગામ પસંદ કરો")})
    await advisory_lock(db, "stock", commencing.id)  # two clerks loading the same village must not oversell it
    available = (await stock_by_commencing(db, [commencing.id])).get(commencing.id)
    available = available.available if available else 0
    if clean["bags"] > available:
        return form({"bags": (f"Only {available} bags are available in {commencing.village}", f"{commencing.village} માં ફક્ત {available} બેગ ઉપલબ્ધ છે")})
    line = TruckLoadLine(trip_id=trip.id, commencing_id=commencing.id, bags=clean["bags"])
    db.add(line)
    await db.flush()
    audit.log(db, user, "create", "truck_load_lines", line.id, dict(trip_id=trip.id, commencing_id=commencing.id, bags=clean["bags"]))
    await db.commit()
    return Response(status_code=204, headers={"HX-Redirect": f"/trips/{trip_id}"})


@router.post("/lines/{line_id}/delete", response_class=HTMLResponse)
async def delete_line(request: Request, line_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    await csrf.validate_csrf(request)
    line = await db.get(TruckLoadLine, line_id)
    if line is None:
        raise HTTPException(404)
    trip = await _get_trip(db, line.trip_id)
    trip_id = trip.id

    def flash(en, gu):
        return render(request, "partials/flash_text.html", kind="error", en=en, gu=gu)

    try:
        await assert_year_open(db, trip.trip_date)
    except YearLockedError as exc:
        msg = YEAR_LOCKED(exc.label)
        return flash(*msg)
    freight = freight_amount(trip.freight_weight_kg, trip.bags - line.bags, trip.rent_per_ton, trip.rent_per_bag)
    problem = _below_paid(await paid_for(db, "truck_trip", trip.id), _final(freight, trip.advance_amount, trip.other_deduction), ("freight", "ભાડા"))
    if problem:
        return flash(*problem)
    audit.log(db, user, "delete", "truck_load_lines", line.id, dict(trip_id=trip_id, commencing_id=line.commencing_id, bags=line.bags))
    await db.delete(line)
    await db.commit()
    return Response(status_code=204, headers={"HX-Redirect": f"/trips/{trip_id}"})


# ================================================================== bilty

@router.get("/{trip_id}/bilty", response_class=HTMLResponse)
async def bilty_page(request: Request, trip_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    trip = await _get_trip(db, trip_id)
    b = trip.bilty
    values = bilty_values(b) if b else dict(bilty_date=today().isoformat(), rate_unit_kg="20", rate_change="0")
    ctx = form_context(fields=await bilty_fields(db), values=values, errors={}, action=f"/trips/{trip.id}/bilty",
                       heading=((f"Edit bilty — {trip.truck.truck_number}", f"બિલ્ટી સુધારો — {trip.truck.truck_number}") if b else (f"New bilty — {trip.truck.truck_number}", f"નવી બિલ્ટી — {trip.truck.truck_number}")),
                       back_url=f"/trips/{trip.id}")
    return render_with_csrf(request, csrf, "master_form_page.html", user=user, **ctx)


@router.post("/{trip_id}/bilty", response_class=HTMLResponse)
async def save_bilty(request: Request, trip_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    await csrf.validate_csrf(request)
    trip = await _get_trip(db, trip_id)
    bilty = trip.bilty
    fields = await bilty_fields(db)
    raw = await read_form(request)
    heading = ("Edit bilty", "બિલ્ટી સુધારો") if bilty else ("New bilty", "નવી બિલ્ટી")
    rerender = lambda errs: render(request, "partials/master_form.html", **form_context(  # noqa: E731
        fields=fields, values=raw, errors=errs, action=f"/trips/{trip_id}/bilty", heading=heading, back_url=f"/trips/{trip_id}"))

    clean, errors = run_validation(BiltyIn, fields, normalize_fields(fields, raw))
    if errors:
        return rerender(errors)
    if clean["merchant_tare_weight"] >= clean["merchant_total_weight"]:
        return rerender({"merchant_tare_weight": ("Empty weight must be less than loaded weight", "ખાલી વજન ભરેલા વજન કરતાં ઓછું હોવું જોઈએ")})
    i_total, i_tare = clean["industry_total_weight"], clean["industry_tare_weight"]
    if (i_total is None) != (i_tare is None):
        return rerender({"industry_tare_weight" if i_tare is None else "industry_total_weight": ("Enter both industry weights, or neither", "કારખાનાના બંને વજન ભરો, અથવા એકેય નહીં")})
    if i_total is not None and i_tare >= i_total:
        return rerender({"industry_tare_weight": ("Empty weight must be less than loaded weight", "ખાલી વજન ભરેલા વજન કરતાં ઓછું હોવું જોઈએ")})
    if clean["rate_change"] and clean["rate_change"] > clean["grain_rate"]:
        return rerender({"rate_change": ("Cannot exceed the sale rate", "વેચાણ ભાવથી વધુ ન હોઈ શકે")})
    broker = await db.get(Broker, clean["broker_id"])
    if broker is None:
        return rerender({"broker_id": ("Unknown broker", "અજ્ઞાત દલાલ")})
    clean["rate_change"] = clean["rate_change"] or 0
    clean["brokerage_amount"] = broker.brokerage_per_truck if clean["brokerage_amount"] is None else clean["brokerage_amount"]
    try:
        clean["business_year"] = await assert_year_open(db, clean["bilty_date"])
        if bilty is not None:
            await assert_year_open(db, bilty.bilty_date)
        await assert_year_open(db, trip.trip_date)
    except YearLockedError as exc:
        return rerender({"bilty_date": YEAR_LOCKED(exc.label)})

    clash = await db.scalar(select(Bilty.id).where(Bilty.business_year == clean["business_year"], Bilty.bill_number == clean["bill_number"], Bilty.id != (bilty.id if bilty else 0)))
    if clash:
        return rerender({"bill_number": ("This bill number is already used in this business year", "આ બિલ નંબર આ વર્ષમાં પહેલેથી વપરાયો છે")})

    # guards: nothing may fall below what has already been paid out / received
    m_net = clean["merchant_total_weight"] - clean["merchant_tare_weight"]
    i_net = None if i_total is None else i_total - i_tare
    if bilty is not None:
        received = (await received_map(db, [bilty.id])).get(bilty.id, 0)
        new_receivable = None if i_net is None else _ceil_div(i_net * (clean["grain_rate"] - clean["rate_change"]), clean["rate_unit_kg"])
        if received and (new_receivable is None or new_receivable < received):
            return rerender({"industry_total_weight": (f"₹{received} is already received against this bilty; the receivable cannot go below that", f"આ બિલ્ટી સામે ₹{received} મળી ગયા છે; લેણાં તેથી ઓછા ન થઈ શકે")})
        problem = _below_paid(await paid_for(db, "bilty_brokerage", bilty.id), clean["brokerage_amount"], ("brokerage", "દલાલી"))
        if problem:
            return rerender({"brokerage_amount": problem})
    freight = freight_amount(i_net if i_net is not None else m_net, trip.bags, trip.rent_per_ton, trip.rent_per_bag)
    problem = _below_paid(await paid_for(db, "truck_trip", trip.id), _final(freight, trip.advance_amount, trip.other_deduction), ("freight", "ભાડા"))
    if problem:
        return rerender({"merchant_total_weight": problem})

    before = None
    if bilty is not None:
        before = bilty_snapshot(bilty)
        for name, value in clean.items():
            setattr(bilty, name, value)
    else:
        bilty = Bilty(trip_id=trip.id, created_by=user.id, **clean)
        db.add(bilty)
    await db.flush()
    audit.log(db, user, "update" if before else "create", "bilties", bilty.id, audit.diff(before, bilty_snapshot(bilty)))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return rerender({"bill_number": GENERIC_ERROR})
    return Response(status_code=204, headers={"HX-Redirect": f"/trips/{trip_id}"})
