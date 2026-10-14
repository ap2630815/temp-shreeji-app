"""Broker bookings: an order booked through a broker for one industry (rate, truck size, percentage deduction).
Truck trips are made against a booking."""

from datetime import date
from typing import Annotated, Literal

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
from app.models import Bilty, BrokerBooking, Brokerage, Industry, TruckTrip, User
from app.services import audit, money
from app.services.receivables import received_map
from app.services.years import YearLockedError, allowed_years, assert_year_open, current_year_label, require_year_visible

router = APIRouter(prefix="/bookings")

TRUCK_SIZES = (10, 15, 20, 25, 30, 35)


class BookingIn(BaseModel):
    booking_date: date
    brokerage_id: int
    industry_id: int
    grain_rate_per_booking_weight: Annotated[int, Field(gt=0, le=1_000_000)]
    truck_size: Literal[10, 15, 20, 25, 30, 35]
    percentage_deduction: Annotated[float, Field(ge=0, le=5)] | None = None
    description: str | None = None


async def booking_fields(db: AsyncSession) -> list[F]:
    brokerages = list((await db.scalars(select(Brokerage))).unique().all())
    brokerages.sort(key=lambda b: (b.broker.broker_name, b.grain.grain_name))
    industries = list((await db.scalars(select(Industry).order_by(Industry.industrialist_name))).all())
    return [
        F("booking_date", "Booking date", "બુકિંગ તારીખ", kind="date", required=True),
        F("brokerage_id", "Broker & grain", "દલાલ અને અનાજ", kind="select", required=True,
          options=tuple((str(b.id), f"{b.broker.broker_name} — {b.grain.grain_name} — ₹{b.brokerage_per_bag}/bag") for b in brokerages),
          help=("Set up in Masters → Brokerage", "માસ્ટર્સ → દલાલીમાં નક્કી કરો")),
        F("industry_id", "Industry", "ઉદ્યોગ", kind="select", required=True,
          options=tuple((str(i.id), f"{i.industrialist_name} — {i.location}") for i in industries)),
        F("grain_rate_per_booking_weight", "Rate per booking weight (₹)", "બુકિંગ વજન દીઠ ભાવ (₹)", kind="int", required=True,
          help=("Per the grain's booking weight (20 or 100 kg)", "અનાજના બુકિંગ વજન (20 અથવા 100 કિલો) દીઠ")),
        F("truck_size", "Truck size (tons)", "ટ્રકની સાઇઝ (ટન)", kind="choice", required=True, choices=TRUCK_SIZES),
        F("percentage_deduction", "Percentage deduction (0–5 %)", "ટકાવારી કપાત (0–5 %)", max_length=5,
          help=("Taken off the bill after the weight is known", "વજન નક્કી થયા પછી બિલમાંથી કપાશે")),
        F("description", "Description", "વર્ણન", kind="textarea"),
    ]


def booking_values(b: BrokerBooking) -> dict:
    return dict(
        booking_date=b.booking_date.isoformat(), brokerage_id=str(b.brokerage_id), industry_id=str(b.industry_id),
        grain_rate_per_booking_weight=str(b.grain_rate_per_booking_weight), truck_size=str(b.truck_size),
        percentage_deduction="" if b.percentage_deduction is None else str(b.percentage_deduction), description=b.description or "",
    )


def booking_snapshot(b: BrokerBooking) -> dict:
    return dict(
        booking_date=b.booking_date, brokerage_id=b.brokerage_id, industry_id=b.industry_id,
        grain_rate_per_booking_weight=b.grain_rate_per_booking_weight, truck_size=b.truck_size,
        percentage_deduction=b.percentage_deduction, description=b.description,
    )


async def _get_booking(db: AsyncSession, booking_id: int) -> BrokerBooking:
    b = await db.get(BrokerBooking, booking_id)
    if b is None:
        raise HTTPException(404)
    return b


async def _trip_count(db: AsyncSession, booking_id: int) -> int:
    return int(await db.scalar(select(func.count()).select_from(TruckTrip).where(TruckTrip.broker_booking_id == booking_id)))


# ---------------------------------------------------------------- list

@router.get("", response_class=HTMLResponse)
async def list_page(
    request: Request, year: str = "", grain_id: int = 0, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    years = allowed_years(user, (await db.scalars(select(BrokerBooking.business_year).distinct())).all())
    year = year if year in years else current_year_label()
    stmt = select(BrokerBooking).where(BrokerBooking.business_year == year)
    if grain_id:
        stmt = stmt.join(Brokerage, Brokerage.id == BrokerBooking.brokerage_id).where(Brokerage.grain_id == grain_id)
    bookings = list((await db.scalars(stmt.order_by(BrokerBooking.booking_date.desc(), BrokerBooking.id.desc()))).unique().all())
    counts = {}
    if bookings:
        rows = await db.execute(select(TruckTrip.broker_booking_id, func.count()).where(TruckTrip.broker_booking_id.in_([b.id for b in bookings])).group_by(TruckTrip.broker_booking_id))
        counts = {bid: int(n) for bid, n in rows.all()}
    return render_with_csrf(request, csrf, "booking_list.html", user=user, bookings=bookings, counts=counts, grain_id=grain_id, year=year,
                            years=years, year_locked=year != current_year_label())


# ---------------------------------------------------------------- create / edit

@router.get("/new", response_class=HTMLResponse)
async def new_page(request: Request, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    ctx = form_context(fields=await booking_fields(db), values=dict(booking_date=today().isoformat()), errors={}, action="/bookings",
                       heading=("New booking", "નવું બુકિંગ"), back_url="/bookings")
    return render_with_csrf(request, csrf, "master_form_page.html", user=user, **ctx)


@router.get("/{booking_id}/edit", response_class=HTMLResponse)
async def edit_page(request: Request, booking_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    b = await _get_booking(db, booking_id)
    locked = {"brokerage_id", "industry_id", "booking_date"} if await _trip_count(db, b.id) else set()
    ctx = form_context(fields=lock(await booking_fields(db), locked), values=booking_values(b), errors={}, action=f"/bookings/{b.id}",
                       heading=("Edit booking", "બુકિંગ સુધારો"), back_url="/bookings")
    return render_with_csrf(request, csrf, "master_form_page.html", user=user, **ctx)


@router.post("", response_class=HTMLResponse)
async def create_booking(request: Request, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    await csrf.validate_csrf(request)
    return await _save(request, None, user, db)


@router.post("/{booking_id}", response_class=HTMLResponse)
async def update_booking(request: Request, booking_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    await csrf.validate_csrf(request)
    return await _save(request, await _get_booking(db, booking_id), user, db)


async def _save(request: Request, b: BrokerBooking | None, user: User, db: AsyncSession):
    b_id = b.id if b else None
    fields = await booking_fields(db)
    raw = await read_form(request)
    has_trips = b is not None and await _trip_count(db, b.id) > 0
    if has_trips:
        fields = lock(fields, {"brokerage_id", "industry_id", "booking_date"})
        stored = booking_values(b)
        raw.update({name: stored[name] for name in ("brokerage_id", "industry_id", "booking_date")})  # trips depend on these
    action = f"/bookings/{b_id}" if b_id else "/bookings"
    heading = ("Edit booking", "બુકિંગ સુધારો") if b else ("New booking", "નવું બુકિંગ")
    rerender = lambda errs: render(request, "partials/master_form.html", **form_context(  # noqa: E731
        fields=fields, values=raw, errors=errs, action=action, heading=heading, back_url="/bookings"))

    clean, errors = run_validation(BookingIn, fields, normalize_fields(fields, raw))
    if errors:
        return rerender(errors)
    brokerage = await db.get(Brokerage, clean["brokerage_id"])
    if brokerage is None:
        return rerender({"brokerage_id": ("Unknown broker / grain", "અજ્ઞાત દલાલ / અનાજ")})
    if await db.get(Industry, clean["industry_id"]) is None:
        return rerender({"industry_id": ("Unknown industry", "અજ્ઞાત ઉદ્યોગ")})
    try:
        clean["business_year"] = await assert_year_open(db, clean["booking_date"])
        if b is not None:
            await assert_year_open(db, b.booking_date)
    except YearLockedError as exc:
        return rerender({"booking_date": YEAR_LOCKED(exc.label)})

    before = None
    if b is not None:
        # a lower rate or a higher deduction must not take a bilty's bill below what the industry already paid
        bilties = list((await db.scalars(select(Bilty).join(TruckTrip, TruckTrip.id == Bilty.truck_trip_id).where(TruckTrip.broker_booking_id == b.id))).unique().all())
        received = await received_map(db, [x.id for x in bilties])
        for x in bilties:
            n = x.industry_net_weight
            if n is None or not received.get(x.id):
                continue
            new = money.receivable_after_percentage_deduction(
                money.receivable_amount(n, x.booking_weight, clean["grain_rate_per_booking_weight"], x.any_rate_change), clean["percentage_deduction"])
            if new < received[x.id]:
                return rerender({"grain_rate_per_booking_weight": (
                    f"Bill #{x.bill_number} already has ₹{received[x.id]} received; this change would take its bill below that",
                    f"બિલ #{x.bill_number} સામે ₹{received[x.id]} મળી ગયા છે; આ ફેરફારથી બિલ તેથી ઓછું થશે")})
        before = booking_snapshot(b)
        for name, value in clean.items():
            setattr(b, name, value)
    else:
        b = BrokerBooking(created_by=user.id, **clean)
        db.add(b)
    await db.flush()
    audit.log(db, user, "update" if before else "create", "broker_bookings", b.id, audit.diff(before, booking_snapshot(b)))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return rerender({"booking_date": GENERIC_ERROR})
    return Response(status_code=204, headers={"HX-Redirect": "/bookings"})
