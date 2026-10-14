"""Truck trips: loading from farmer entries, the bilty (weights) and what follows from it.

A trip belongs to a broker booking, which fixes the grain, the industry, the sale rate and the broker."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi_csrf_protect import CsrfProtect
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.api.formkit import GENERIC_ERROR, YEAR_LOCKED, form_context, lock, normalize_fields, read_form, today
from app.api.masters_config import F, run_validation
from app.core.db import get_db
from app.core.templating import render, render_with_csrf
from app.models import (
    Bilty, BrokerBooking, Brokerage, LabourGroup, PurchaseFarmerEntry, PurchaseInfo, Transporter, Truck, TruckLoadLine, TruckTrip, User,
)
from app.services import audit, money
from app.services.locks import advisory_lock
from app.services.payables import paid_for
from app.services.receivables import received_map
from app.services.stock import renumber_remaining, stock_by_entry
from app.services.years import YearLockedError, allowed_years, assert_year_open, current_year_label, require_year_visible

router = APIRouter(prefix="/trips")

INT_MAX = 100_000_000
WEIGHT_MAX = 200_000  # kg; no truck carries more
SHORT_WARN_PCT = 1  # highlight a weight shortage at or above this percentage


def _int(ge=0, gt=None, le=INT_MAX):
    return Annotated[int, Field(ge=ge, le=le)] if gt is None else Annotated[int, Field(gt=gt, le=le)]


# ================================================================== trip form

class TripIn(BaseModel):
    trip_date: date
    broker_booking_id: int
    truck_id: int
    transporter_id: int
    labour_group_id: int
    rent_per_ton: _int() | None = None
    rent_per_bag: _int() | None = None
    advance_amount: _int() | None = None
    other_payable: _int() | None = None
    other_deduction: _int() | None = None
    description: str | None = None


ZERO_FIELDS = ("rent_per_ton", "rent_per_bag", "advance_amount", "other_payable", "other_deduction")


async def _options(db: AsyncSession, model, order):
    return list((await db.scalars(select(model).order_by(order))).unique().all())


async def trip_fields(db: AsyncSession) -> list[F]:
    trucks, transporters = await _options(db, Truck, Truck.truck_number), await _options(db, Transporter, Transporter.pet_name)
    groups = await _options(db, LabourGroup, LabourGroup.group_name)
    bookings = list((await db.scalars(select(BrokerBooking).order_by(BrokerBooking.booking_date.desc(), BrokerBooking.id.desc()).limit(300))).unique().all())
    return [
        F("trip_date", "Date", "તારીખ", kind="date", required=True),
        F("broker_booking_id", "Booking (broker · grain → industry)", "બુકિંગ (દલાલ · અનાજ → ઉદ્યોગ)", kind="select", required=True,
          options=tuple((str(b.id), f"{b.booking_date} · {b.brokerage.broker.broker_name} · {b.grain.grain_name} → {b.industry.industrialist_name} · {b.truck_size}t") for b in bookings),
          help=("Fixes the grain, the industry, the rate and the broker for this trip", "આ ટ્રીપ માટે અનાજ, ઉદ્યોગ, ભાવ અને દલાલ નક્કી કરે છે")),
        F("truck_id", "Truck", "ટ્રક", kind="select", required=True, options=tuple((str(t.id), f"{t.truck_number} — {t.driver_name}") for t in trucks)),
        F("transporter_id", "Transport", "ટ્રાન્સપોર્ટ", kind="select", required=True, options=tuple((str(t.id), f"{t.pet_name} — {t.location}") for t in transporters)),
        F("labour_group_id", "Loading labour", "લોડિંગ મજૂર", kind="select", required=True, options=tuple((str(g.id), g.group_name) for g in groups)),
        F("rent_per_ton", "Rent per ton (₹)", "ટન દીઠ ભાડું (₹)", kind="int",
          help=("Fill exactly one of rent per ton / rent per bag", "ટન ભાડું અથવા બેગ ભાડું — બેમાંથી એક જ ભરો")),
        F("rent_per_bag", "Rent per bag (₹)", "બેગ દીઠ ભાડું (₹)", kind="int"),
        F("advance_amount", "Advance given to driver (₹)", "ડ્રાઇવરને આપેલ એડવાન્સ (₹)", kind="int"),
        F("other_payable", "Other payable to the truck (₹)", "ટ્રકને અન્ય ચૂકવવાપાત્ર (₹)", kind="int"),
        F("other_deduction", "Other deduction (₹)", "અન્ય કપાત (₹)", kind="int"),
        F("description", "Description", "વર્ણન", kind="textarea"),
    ]


def trip_values(t: TruckTrip) -> dict:
    return dict(
        trip_date=t.trip_date.isoformat(), broker_booking_id=str(t.broker_booking_id), truck_id=str(t.truck_id), transporter_id=str(t.transporter_id),
        labour_group_id=str(t.labour_group_id), rent_per_ton=str(t.rent_per_ton), rent_per_bag=str(t.rent_per_bag), advance_amount=str(t.advance_amount),
        other_payable=str(t.other_payable), other_deduction=str(t.other_deduction), description=t.description or "",
    )


def trip_snapshot(t: TruckTrip) -> dict:
    return dict(
        trip_date=t.trip_date, broker_booking_id=t.broker_booking_id, truck_id=t.truck_id, transporter_id=t.transporter_id, labour_group_id=t.labour_group_id,
        rent_per_ton=t.rent_per_ton, rent_per_bag=t.rent_per_bag, advance_amount=t.advance_amount, other_payable=t.other_payable,
        other_deduction=t.other_deduction, description=t.description,
    )


def _locked_trip_fields(trip: TruckTrip | None) -> set[str]:
    # the loaded bags and the bilty are tied to the booking's grain / industry / rate
    return {"broker_booking_id"} if trip is not None and (trip.load_lines or trip.bilty is not None) else set()


# ================================================================== bilty form

class BiltyIn(BaseModel):
    bill_number: _int(gt=0)
    bilty_date: date
    any_rate_change: _int() | None = None
    merchant_total_weight: _int(gt=0, le=WEIGHT_MAX)
    merchant_tare_weight: _int(le=WEIGHT_MAX)
    industry_total_weight: _int(gt=0, le=WEIGHT_MAX) | None = None
    industry_tare_weight: _int(le=WEIGHT_MAX) | None = None
    description: str | None = None


def bilty_fields() -> list[F]:
    kg = ("kg", "કિલો")
    return [
        F("bill_number", "Bill number", "બિલ નંબર", kind="int", required=True, help=("Unique within the business year", "વ્યવસાય વર્ષમાં અનન્ય")),
        F("bilty_date", "Bilty date", "બિલ્ટી તારીખ", kind="date", required=True),
        F("any_rate_change", "Rate reduction after delivery (₹)", "ડિલિવરી પછી ભાવ ઘટાડો (₹)", kind="int",
          help=("Taken off the booked rate", "બુક કરેલા ભાવમાંથી ઘટાડો")),
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
        bill_number=str(b.bill_number), bilty_date=b.bilty_date.isoformat(), any_rate_change=str(b.any_rate_change),
        merchant_total_weight=str(b.merchant_total_weight), merchant_tare_weight=str(b.merchant_tare_weight),
        industry_total_weight=n(b.industry_total_weight), industry_tare_weight=n(b.industry_tare_weight), description=b.description or "",
    )


def bilty_snapshot(b: Bilty) -> dict:
    return dict(
        bill_number=b.bill_number, bilty_date=b.bilty_date, total_bags_in_truck=b.total_bags_in_truck, any_rate_change=b.any_rate_change,
        merchant_total_weight=b.merchant_total_weight, merchant_tare_weight=b.merchant_tare_weight, industry_total_weight=b.industry_total_weight,
        industry_tare_weight=b.industry_tare_weight, description=b.description,
    )


# ================================================================== load line form

class LineIn(BaseModel):
    purchase_farmer_entry_id: int
    no_of_loaded_bags: _int(gt=0) | None = None  # blank: load everything still unloaded in the entry


async def line_fields(db: AsyncSession, trip: TruckTrip) -> list[F]:
    on_trip = {line.purchase_farmer_entry_id for line in trip.load_lines}
    entries = list((await db.scalars(
        select(PurchaseFarmerEntry).join(PurchaseInfo, PurchaseInfo.id == PurchaseFarmerEntry.purchase_info_id)
        .where(PurchaseInfo.grain_id == trip.grain.id).order_by(PurchaseFarmerEntry.purchase_entry_date.desc(), PurchaseFarmerEntry.id.desc()).limit(500)
    )).unique().all())
    stock = await stock_by_entry(db, [e.id for e in entries])
    options = tuple(
        (str(e.id), f"{e.purchase_info.village.village_name} · {e.farmer.farmer_name} · {e.purchase_entry_date} — {stock[e.id].available} bags left")
        for e in entries if e.id in stock and stock[e.id].available > 0 and e.id not in on_trip
    )
    return [
        F("purchase_farmer_entry_id", "Load from (village · farmer)", "ક્યાંથી ભર્યું (ગામ · ખેડૂત)", kind="select", required=True, options=options),
        F("no_of_loaded_bags", "Bags loaded", "ભરેલી બેગ", kind="int",
          help=("Leave blank to load all the bags left in that entry", "ખાલી રાખો તો તે એન્ટ્રીની બાકી બધી બેગ ભરાશે")),
    ]


# ================================================================== helpers

async def _get_trip(db: AsyncSession, trip_id: int) -> TruckTrip:
    trip = await db.get(TruckTrip, trip_id)
    if trip is None:
        raise HTTPException(404)
    return trip


def _total(weight_kg: int | None, bags: int, rent_per_ton: int, rent_per_bag: int, advance: int, other_payable: int, deduction: int) -> int:
    return money.truck_trip_total_amount(money.trip_total(weight_kg, bags, rent_per_ton, rent_per_bag), advance, other_payable, deduction)


def _below_paid(paid: int, new_amount: int, what: tuple[str, str]) -> tuple[str, str] | None:
    if new_amount < paid:
        return (f"₹{paid} is already paid as {what[0]}; this change would take it below that", f"{what[1]} તરીકે ₹{paid} ચૂકવાઈ ગયા છે; આ ફેરફારથી તે ઓછું થશે")
    return None


async def _sync_bilty_bags(db: AsyncSession, trip: TruckTrip) -> None:
    """bilties.total_bags_in_truck always equals the sum of the trip's loaded bags."""
    if trip.bilty is not None:
        trip.bilty.total_bags_in_truck = sum(line.no_of_loaded_bags for line in trip.load_lines)


async def _years_with_trips(db: AsyncSession, user: User) -> list[str]:
    return allowed_years(user, (await db.scalars(select(TruckTrip.business_year).distinct())).all())


# ================================================================== list

@router.get("", response_class=HTMLResponse)
async def list_page(
    request: Request, year: str = "", grain_id: int = 0, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    years = await _years_with_trips(db, user)
    year = year if year in years else current_year_label()
    stmt = select(TruckTrip).where(TruckTrip.business_year == year)
    if grain_id:
        stmt = (stmt.join(BrokerBooking, BrokerBooking.id == TruckTrip.broker_booking_id)
                .join(Brokerage, Brokerage.id == BrokerBooking.brokerage_id).where(Brokerage.grain_id == grain_id))
    trips = list((await db.scalars(stmt.order_by(TruckTrip.trip_date.desc(), TruckTrip.id.desc()))).unique().all())
    return render_with_csrf(request, csrf, "trip_list.html", user=user, trips=trips, grain_id=grain_id, year=year, years=years,
                            year_locked=year != current_year_label(), warn_pct=SHORT_WARN_PCT)


# ================================================================== trip create / edit

@router.get("/new", response_class=HTMLResponse)
async def new_page(request: Request, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    ctx = form_context(fields=await trip_fields(db),
                       values=dict(trip_date=today().isoformat(), rent_per_ton="0", rent_per_bag="0", advance_amount="0", other_payable="0", other_deduction="0"),
                       errors={}, action="/trips", heading=("New truck trip", "નવી ટ્રક ટ્રીપ"), back_url="/trips")
    return render_with_csrf(request, csrf, "master_form_page.html", user=user, **ctx)


@router.get("/{trip_id}/edit", response_class=HTMLResponse)
async def edit_page(request: Request, trip_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    trip = await _get_trip(db, trip_id)
    fields = lock(await trip_fields(db), _locked_trip_fields(trip))
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
    locked = _locked_trip_fields(trip)
    if locked:
        fields = lock(fields, locked)
        raw["broker_booking_id"] = str(trip.broker_booking_id)  # a trip with loaded bags / a bilty keeps its booking
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
    if (clean["rent_per_ton"] > 0) == (clean["rent_per_bag"] > 0):
        return rerender({"rent_per_ton": ("Fill exactly one of rent per ton / rent per bag", "ટન ભાડું અથવા બેગ ભાડું — બેમાંથી એક જ ભરો")})
    for name, model in (("broker_booking_id", BrokerBooking), ("truck_id", Truck), ("transporter_id", Transporter), ("labour_group_id", LabourGroup)):
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
        total = _total(trip.freight_weight_kg, trip.bags, clean["rent_per_ton"], clean["rent_per_bag"], clean["advance_amount"], clean["other_payable"], clean["other_deduction"])
        problem = _below_paid(await paid_for(db, "truck", trip.id), total, ("freight", "ભાડા"))
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
    require_year_visible(user, trip.business_year)
    bilty = trip.bilty
    line_form = form_context(fields=await line_fields(db, trip), values={}, errors={}, action=f"/trips/{trip.id}/lines", heading=("Add load", "લોડ ઉમેરો"), back_url=f"/trips/{trip.id}")
    ctx = dict(
        trip=trip, bilty=bilty, line_form=line_form, warn_pct=SHORT_WARN_PCT,
        freight_paid=await paid_for(db, "truck", trip.id),
        brokerage_paid=await paid_for(db, "broker", bilty.id) if bilty else 0,
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
        return form({"no_of_loaded_bags": YEAR_LOCKED(exc.label)})
    entry = await db.get(PurchaseFarmerEntry, clean["purchase_farmer_entry_id"])
    if entry is None or entry.purchase_info.grain_id != trip.grain.id:
        return form({"purchase_farmer_entry_id": ("Pick an entry with the same grain as this trip", "આ ટ્રીપના અનાજવાળી એન્ટ્રી પસંદ કરો")})
    if any(line.purchase_farmer_entry_id == entry.id for line in trip.load_lines):
        return form({"purchase_farmer_entry_id": ("This entry is already loaded on this trip", "આ એન્ટ્રી આ ટ્રીપમાં પહેલેથી ભરાઈ ગઈ છે")})
    await advisory_lock(db, "stock", entry.id)  # two clerks loading the same entry must not oversell it
    available = (await stock_by_entry(db, [entry.id])).get(entry.id)
    available = available.available if available else 0
    bags = clean["no_of_loaded_bags"] or available
    if bags <= 0 or bags > available:
        return form({"no_of_loaded_bags": (f"Only {available} bags are left in this entry", f"આ એન્ટ્રીમાં ફક્ત {available} બેગ બાકી છે")})
    line = TruckLoadLine(trip_id=trip.id, purchase_farmer_entry_id=entry.id, no_of_loaded_bags=bags, total_remaining_bags=available - bags)
    db.add(line)
    await db.flush()
    await renumber_remaining(db, entry.id)
    if trip.bilty is not None:
        trip.bilty.total_bags_in_truck = sum(l.no_of_loaded_bags for l in trip.load_lines) + bags
    audit.log(db, user, "create", "truck_load_lines", line.id, dict(trip_id=trip.id, purchase_farmer_entry_id=entry.id, no_of_loaded_bags=bags))
    await db.commit()
    return Response(status_code=204, headers={"HX-Redirect": f"/trips/{trip_id}"})


@router.post("/lines/{line_id}/delete", response_class=HTMLResponse)
async def delete_line(request: Request, line_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    await csrf.validate_csrf(request)
    line = await db.get(TruckLoadLine, line_id)
    if line is None:
        raise HTTPException(404)
    trip = await _get_trip(db, line.trip_id)
    trip_id, entry_id, bags = trip.id, line.purchase_farmer_entry_id, line.no_of_loaded_bags

    def flash(en, gu):
        return render(request, "partials/flash_text.html", kind="error", en=en, gu=gu)

    try:
        await assert_year_open(db, trip.trip_date)
    except YearLockedError as exc:
        return flash(*YEAR_LOCKED(exc.label))
    new_bags = trip.bags - bags
    total = _total(trip.freight_weight_kg, new_bags, trip.rent_per_ton, trip.rent_per_bag, trip.advance_amount, trip.other_payable, trip.other_deduction)
    problem = _below_paid(await paid_for(db, "truck", trip.id), total, ("freight", "ભાડા"))
    if problem:
        return flash(*problem)
    if trip.bilty is not None:
        per_bag = trip.bilty.booking.brokerage.brokerage_per_bag
        problem = _below_paid(await paid_for(db, "broker", trip.bilty.id), money.brokerage_amount(new_bags, per_bag), ("brokerage", "દલાલી"))
        if problem:
            return flash(*problem)
    audit.log(db, user, "delete", "truck_load_lines", line.id, dict(trip_id=trip_id, purchase_farmer_entry_id=entry_id, no_of_loaded_bags=bags))
    await db.delete(line)
    await db.flush()
    await renumber_remaining(db, entry_id)
    if trip.bilty is not None:
        trip.bilty.total_bags_in_truck = new_bags
    await db.commit()
    return Response(status_code=204, headers={"HX-Redirect": f"/trips/{trip_id}"})


# ================================================================== bilty

@router.get("/{trip_id}/bilty", response_class=HTMLResponse)
async def bilty_page(request: Request, trip_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    trip = await _get_trip(db, trip_id)
    b = trip.bilty
    values = bilty_values(b) if b else dict(bilty_date=today().isoformat(), any_rate_change="0")
    ctx = form_context(fields=bilty_fields(), values=values, errors={}, action=f"/trips/{trip.id}/bilty",
                       heading=((f"Edit bilty — {trip.truck.truck_number}", f"બિલ્ટી સુધારો — {trip.truck.truck_number}") if b else (f"New bilty — {trip.truck.truck_number}", f"નવી બિલ્ટી — {trip.truck.truck_number}")),
                       back_url=f"/trips/{trip.id}")
    return render_with_csrf(request, csrf, "master_form_page.html", user=user, **ctx)


@router.post("/{trip_id}/bilty", response_class=HTMLResponse)
async def save_bilty(request: Request, trip_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    await csrf.validate_csrf(request)
    trip = await _get_trip(db, trip_id)
    bilty = trip.bilty
    fields = bilty_fields()
    raw = await read_form(request)
    heading = ("Edit bilty", "બિલ્ટી સુધારો") if bilty else ("New bilty", "નવી બિલ્ટી")
    rerender = lambda errs: render(request, "partials/master_form.html", **form_context(  # noqa: E731
        fields=fields, values=raw, errors=errs, action=f"/trips/{trip_id}/bilty", heading=heading, back_url=f"/trips/{trip_id}"))

    clean, errors = run_validation(BiltyIn, fields, normalize_fields(fields, raw))
    if errors:
        return rerender(errors)
    bags = trip.bags
    if bags <= 0:
        return rerender({"bill_number": ("Add the loaded bags to the trip first", "પહેલા ટ્રીપમાં ભરેલી બેગ ઉમેરો")})
    if clean["merchant_tare_weight"] >= clean["merchant_total_weight"]:
        return rerender({"merchant_tare_weight": ("Empty weight must be less than loaded weight", "ખાલી વજન ભરેલા વજન કરતાં ઓછું હોવું જોઈએ")})
    i_total, i_tare = clean["industry_total_weight"], clean["industry_tare_weight"]
    if (i_total is None) != (i_tare is None):
        return rerender({"industry_tare_weight" if i_tare is None else "industry_total_weight": ("Enter both industry weights, or neither", "કારખાનાના બંને વજન ભરો, અથવા એકેય નહીં")})
    if i_total is not None and i_tare >= i_total:
        return rerender({"industry_tare_weight": ("Empty weight must be less than loaded weight", "ખાલી વજન ભરેલા વજન કરતાં ઓછું હોવું જોઈએ")})
    booking = trip.broker_booking
    clean["any_rate_change"] = clean["any_rate_change"] or 0
    if clean["any_rate_change"] > booking.grain_rate_per_booking_weight:
        return rerender({"any_rate_change": ("Cannot exceed the booked rate", "બુક કરેલા ભાવથી વધુ ન હોઈ શકે")})
    clean["total_bags_in_truck"] = bags
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
        new_receivable = None if i_net is None else money.receivable_after_percentage_deduction(
            money.receivable_amount(i_net, booking.brokerage.grain.booking_weight, booking.grain_rate_per_booking_weight, clean["any_rate_change"]), booking.percentage_deduction)
        if received and (new_receivable is None or new_receivable < received):
            return rerender({"industry_total_weight": (f"₹{received} is already received against this bilty; the receivable cannot go below that", f"આ બિલ્ટી સામે ₹{received} મળી ગયા છે; લેણાં તેથી ઓછા ન થઈ શકે")})
    total = _total(i_net if i_net is not None else m_net, bags, trip.rent_per_ton, trip.rent_per_bag, trip.advance_amount, trip.other_payable, trip.other_deduction)
    problem = _below_paid(await paid_for(db, "truck", trip.id), total, ("freight", "ભાડા"))
    if problem:
        return rerender({"merchant_total_weight": problem})

    before = None
    if bilty is not None:
        before = bilty_snapshot(bilty)
        for name, value in clean.items():
            setattr(bilty, name, value)
    else:
        bilty = Bilty(truck_trip_id=trip.id, created_by=user.id, **clean)
        db.add(bilty)
    await db.flush()
    audit.log(db, user, "update" if before else "create", "bilties", bilty.id, audit.diff(before, bilty_snapshot(bilty)))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return rerender({"bill_number": GENERIC_ERROR})
    return Response(status_code=204, headers={"HX-Redirect": f"/trips/{trip_id}"})
