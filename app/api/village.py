"""Commencing (village deal) and farmer weighing entries."""

from datetime import date, timedelta
from types import SimpleNamespace
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
from app.models import BusinessYear, Commencing, Farmer, Grain, LabourGroup, PurchaseEntry, User
from app.services import audit
from app.services.ledger import commencing_entries, entry_views, paid_for_entry, totals
from app.services.money import payable_amount
from app.services.years import YearLockedError, assert_year_open, business_year_of

router = APIRouter(prefix="/commencings")

NET_WEIGHTS = (35, 50, 70, 100)
INT_MAX = 100_000_000


# ---------------------------------------------------------------- commencing forms

class CommencingIn(BaseModel):
    commencing_date: date
    village: Annotated[str, Field(min_length=1, max_length=100)]
    grain_id: int
    rate_per_20kg: Annotated[int, Field(gt=0, le=1_000_000)]
    net_weight: Literal[35, 50, 70, 100] | None = None
    pay_after_days: Annotated[int, Field(ge=0, le=3650)]
    terms: str | None = None
    description: str | None = None


def commencing_fields(grains: list[Grain]) -> list[F]:
    return [
        F("commencing_date", "Date", "તારીખ", kind="date", required=True),
        F("village", "Village", "ગામ", required=True, max_length=100),
        F("grain_id", "Grain", "અનાજ", kind="select", required=True, options=tuple((str(g.id), f"{g.name} / {g.name_gu or ''}") for g in grains)),
        F("rate_per_20kg", "Rate per 20 kg (₹)", "20 કિલો દીઠ ભાવ (₹)", kind="int", required=True),
        F("net_weight", "Net weight per filled bag (kg)", "ભરેલી બેગનું ચોખ્ખું વજન (કિલો)", kind="choice", choices=NET_WEIGHTS,
          help=("Leave blank to use the grain's default", "ખાલી રાખો તો અનાજનું ડિફોલ્ટ વપરાશે")),
        F("pay_after_days", "Pay after (days)", "ચુકવણી (દિવસ પછી)", kind="int", required=True),
        F("terms", "Terms & conditions", "શરતો", kind="textarea",
          help=("Leave blank to copy the grain's default terms", "ખાલી રાખો તો અનાજની ડિફોલ્ટ શરતો લેવાશે")),
        F("description", "Description", "વર્ણન", kind="textarea"),
    ]


def commencing_values(c: Commencing) -> dict:
    return dict(
        commencing_date=c.commencing_date.isoformat(), village=c.village, grain_id=str(c.grain_id),
        rate_per_20kg=str(c.rate_per_20kg), net_weight=str(c.net_weight), pay_after_days=str(c.pay_after_days),
        terms=c.terms or "", description=c.description or "",
    )


def commencing_snapshot(c: Commencing) -> dict:
    return dict(
        commencing_date=c.commencing_date, village=c.village, grain_id=c.grain_id, rate_per_20kg=c.rate_per_20kg,
        net_weight=c.net_weight, pay_after_days=c.pay_after_days, terms=c.terms, description=c.description,
    )


# ---------------------------------------------------------------- entry forms

class EntryIn(BaseModel):
    farmer_id: int
    labour_group_id: int
    entry_date: date
    filled_bags: Annotated[int, Field(ge=0, le=INT_MAX)]
    extra_kilos: Annotated[int, Field(ge=0, le=INT_MAX)] | None = None  # blank means 0
    raw_weight: Annotated[int, Field(ge=0, le=INT_MAX)] | None = None
    borrowing: Annotated[int, Field(ge=0, le=INT_MAX)] | None = None  # blank means 0
    description: str | None = None


def entry_fields(farmers: list[Farmer], groups: list[LabourGroup]) -> list[F]:
    return [
        F("farmer_id", "Farmer", "ખેડૂત", kind="select", required=True,
          options=tuple((str(f.id), f"{f.name} — {f.village} — {f.mobile}") for f in farmers)),
        F("labour_group_id", "Labour group", "મજૂર જૂથ", kind="select", required=True,
          options=tuple((str(g.id), f"{g.group_name} — {g.name}") for g in groups)),
        F("entry_date", "Date", "તારીખ", kind="date", required=True),
        F("filled_bags", "Filled bags", "ભરેલી બેગ", kind="int", required=True),
        F("extra_kilos", "Extra kilos (loose, beyond full bags)", "વધારાના કિલો (પૂરી બેગ ઉપરાંત)", kind="int"),
        F("raw_weight", "Raw weight (kg) — reference only", "કાચું વજન (કિલો) — ફક્ત સંદર્ભ માટે", kind="int",
          help=("Never used in the payment", "ચુકવણીમાં ક્યારેય ગણાતું નથી")),
        F("borrowing", "Borrowing / advance to deduct (₹)", "ઉધાર / એડવાન્સ કાપવાના (₹)", kind="int"),
        F("description", "Description (e.g. 2 quality grains, warning)", "વર્ણન (દા.ત. બે ગુણવત્તા, ચેતવણી)", kind="textarea"),
    ]


def entry_values(e: PurchaseEntry) -> dict:
    return dict(
        farmer_id=str(e.farmer_id), labour_group_id=str(e.labour_group_id), entry_date=e.entry_date.isoformat(),
        filled_bags=str(e.filled_bags), extra_kilos=str(e.extra_kilos),
        raw_weight="" if e.raw_weight is None else str(e.raw_weight), borrowing=str(e.borrowing), description=e.description or "",
    )


def entry_snapshot(e: PurchaseEntry) -> dict:
    return dict(
        farmer_id=e.farmer_id, labour_group_id=e.labour_group_id, entry_date=e.entry_date, filled_bags=e.filled_bags,
        extra_kilos=e.extra_kilos, raw_weight=e.raw_weight, borrowing=e.borrowing, payable_amount=e.payable_amount,
        due_date=e.due_date, description=e.description,
    )


def recalc(entry: PurchaseEntry, c: Commencing) -> None:
    """Rate, bag weight and pay-after always come from the commencing; entries cannot override them."""
    entry.payable_amount = payable_amount(entry.filled_bags, entry.extra_kilos, c.net_weight, c.rate_per_20kg)
    entry.due_date = entry.entry_date + timedelta(days=c.pay_after_days)


async def _get_commencing(db: AsyncSession, commencing_id: int) -> Commencing:
    c = await db.get(Commencing, commencing_id)
    if c is None:
        raise HTTPException(404)
    return c


async def _years_with_data(db: AsyncSession) -> list[str]:
    rows = (await db.scalars(select(Commencing.business_year).distinct())).all()
    return sorted({business_year_of(today()), *rows}, reverse=True)


# ---------------------------------------------------------------- list

@router.get("", response_class=HTMLResponse)
async def list_page(
    request: Request, year: str = "", grain_id: int = 0, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    years = await _years_with_data(db)
    year = year if year in years else business_year_of(today())
    stmt = select(Commencing).where(Commencing.business_year == year)
    if grain_id:
        stmt = stmt.where(Commencing.grain_id == grain_id)
    commencings = (
        await db.scalars(stmt.order_by(Commencing.commencing_date.desc(), Commencing.id.desc()))
    ).all()
    views = await entry_views(db, commencing_ids=[c.id for c in commencings]) if commencings else []
    per: dict[int, list] = {c.id: [] for c in commencings}
    for v in views:
        per[v.entry.commencing_id].append(v)
    now = today()
    rows = [(c, totals(per[c.id], now)) for c in commencings]
    locked = await db.get(BusinessYear, year)
    return render_with_csrf(
        request, csrf, "commencing_list.html", user=user, rows=rows, grain_id=grain_id, year=year, years=years, year_locked=bool(locked and locked.is_locked)
    )


# ---------------------------------------------------------------- commencing create / edit

@router.get("/new", response_class=HTMLResponse)
async def new_page(request: Request, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    grains = (await db.scalars(select(Grain).order_by(Grain.name))).all()
    ctx = form_context(
        fields=commencing_fields(list(grains)), values=dict(commencing_date=today().isoformat()), errors={},
        action="/commencings", heading=("New commencing", "નવું કમેન્સિંગ"), back_url="/commencings",
    )
    return render_with_csrf(request, csrf, "master_form_page.html", user=user, **ctx)


@router.get("/{commencing_id}/edit", response_class=HTMLResponse)
async def edit_page(
    request: Request, commencing_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    c = await _get_commencing(db, commencing_id)
    grains = (await db.scalars(select(Grain).order_by(Grain.name))).all()
    fields = lock(commencing_fields(list(grains)), await _locked_commencing_fields(db, c, user))
    ctx = form_context(
        fields=fields, values=commencing_values(c), errors={}, action=f"/commencings/{c.id}",
        heading=(f"Edit commencing: {c.village}", f"કમેન્સિંગ સુધારો: {c.village}"), back_url=f"/commencings/{c.id}",
    )
    return render_with_csrf(request, csrf, "master_form_page.html", user=user, **ctx)


async def _locked_commencing_fields(db: AsyncSession, c: Commencing, user: User) -> set[str]:
    has_entries = bool(await db.scalar(select(func.count()).select_from(PurchaseEntry).where(PurchaseEntry.commencing_id == c.id)))
    locked: set[str] = set()
    if has_entries:
        locked |= {"grain_id", "commencing_date"}  # entries depend on both
        if user.role != "owner":
            locked |= {"rate_per_20kg", "net_weight", "pay_after_days"}  # only the owner may reprice
    return locked


@router.post("", response_class=HTMLResponse)
async def create_commencing(
    request: Request, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    await csrf.validate_csrf(request)
    return await _save_commencing(request, None, user, db)


@router.post("/{commencing_id}", response_class=HTMLResponse)
async def update_commencing(
    request: Request, commencing_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    await csrf.validate_csrf(request)
    return await _save_commencing(request, commencing_id, user, db)


async def _save_commencing(request: Request, commencing_id: int | None, user: User, db: AsyncSession):
    user_id, username = user.id, user.username
    grains = list((await db.scalars(select(Grain).order_by(Grain.name))).all())
    c = await _get_commencing(db, commencing_id) if commencing_id else None
    c_id = c.id if c else None  # read now: a rollback expires `c`
    fields = commencing_fields(grains)
    raw = await read_form(request)
    locked: set[str] = set()
    if c is not None:
        locked = await _locked_commencing_fields(db, c, user)
        stored = commencing_values(c)
        raw.update({name: stored[name] for name in locked})  # locked fields keep their stored value
    fields = lock(fields, locked)
    clean, errors = run_validation(CommencingIn, fields, normalize_fields(fields, raw))
    heading = ("Edit commencing", "કમેન્સિંગ સુધારો") if c else ("New commencing", "નવું કમેન્સિંગ")
    action = f"/commencings/{c_id}" if c_id else "/commencings"

    def rerender(errs):
        return render(request, "partials/master_form.html", **form_context(
            fields=fields, values=raw, errors=errs, action=action, heading=heading,
            back_url=f"/commencings/{c_id}" if c_id else "/commencings"))

    if errors:
        return rerender(errors)

    grain = await db.get(Grain, clean["grain_id"])
    if grain is None:
        return rerender({"grain_id": ("Unknown grain", "અજ્ઞાત અનાજ")})
    clean["net_weight"] = clean["net_weight"] or grain.default_net_weight
    clean["terms"] = clean["terms"] or grain.default_terms
    try:
        clean["business_year"] = await assert_year_open(db, clean["commencing_date"])
        if c is not None:  # also the stored year must be open, otherwise a locked year could be edited
            await assert_year_open(db, c.commencing_date)
    except YearLockedError as exc:
        return rerender({"commencing_date": YEAR_LOCKED(exc.label)})

    before = commencing_snapshot(c) if c else None
    if c is None:
        c = Commencing(created_by=user_id, **clean)
        db.add(c)
        await db.flush()
    else:
        for name, value in clean.items():
            setattr(c, name, value)
        problem = await _reprice_entries(db, c)
        if problem:
            await db.rollback()
            return rerender({"rate_per_20kg": problem})
    audit.log(db, user, "update" if before else "create", "commencings", c.id, audit.diff(before, commencing_snapshot(c)))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return rerender({"village": GENERIC_ERROR})
    return Response(status_code=204, headers={"HX-Redirect": f"/commencings/{c.id}"})


async def _reprice_entries(db: AsyncSession, c: Commencing) -> tuple[str, str] | None:
    """Re-derive every entry after a rate/weight/pay-after change; refuse if it would drop below what is already paid."""
    for view in await commencing_entries(db, c.id):
        e = view.entry
        recalc(e, c)
        if e.borrowing > e.payable_amount or e.net_payable < view.paid:
            return (
                f"This change would take {e.farmer.name}'s amount below what is already paid / borrowed",
                f"આ ફેરફારથી {e.farmer.name}ની રકમ ચૂકવેલી / ઉધાર રકમથી ઓછી થશે",
            )
    return None


# ---------------------------------------------------------------- detail

@router.get("/{commencing_id}", response_class=HTMLResponse)
async def detail_page(
    request: Request, commencing_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    c = await _get_commencing(db, commencing_id)
    views = await commencing_entries(db, c.id)
    now = today()
    return render_with_csrf(request, csrf, "commencing_detail.html", user=user, c=c, views=views, totals=totals(views, now), today=now)


# ---------------------------------------------------------------- entries

async def _entry_form_data(db: AsyncSession, c: Commencing, show_all: bool, keep_farmer_id: int | None = None):
    base = select(Farmer).order_by(Farmer.name)
    in_village = (await db.scalars(base.where(func.lower(Farmer.village) == c.village.lower()))).all()
    farmers = list((await db.scalars(base)).all()) if (show_all or not in_village) else list(in_village)
    if keep_farmer_id and all(f.id != keep_farmer_id for f in farmers):
        farmers.append(await db.get(Farmer, keep_farmer_id))
    groups = list((await db.scalars(select(LabourGroup).order_by(LabourGroup.group_name))).all())
    return farmers, groups, bool(in_village) and not show_all


def _entry_ctx(c, fields, values, errors, action, heading, village_filtered, show_all_url, preview=True):
    return form_context(
        fields=fields, values=values, errors=errors, action=action, heading=heading, back_url=f"/commencings/{c.id}",
        c=c, village_filtered=village_filtered, show_all_url=show_all_url, preview=preview,
    )


@router.get("/{commencing_id}/entries/new", response_class=HTMLResponse)
async def new_entry_page(
    request: Request, commencing_id: int, all: int = 0, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    c = await _get_commencing(db, commencing_id)
    farmers, groups, filtered = await _entry_form_data(db, c, bool(all))
    ctx = _entry_ctx(
        c, entry_fields(farmers, groups), dict(entry_date=today().isoformat(), extra_kilos="0", borrowing="0"), {},
        f"/commencings/{c.id}/entries" + ("?all=1" if all else ""),
        (f"Add farmer entry — {c.village}", f"ખેડૂત એન્ટ્રી ઉમેરો — {c.village}"), filtered, f"/commencings/{c.id}/entries/new?all=1",
    )
    return render_with_csrf(request, csrf, "entry_form_page.html", user=user, **ctx)


@router.get("/entries/{entry_id}/edit", response_class=HTMLResponse)
async def edit_entry_page(
    request: Request, entry_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    e = await db.get(PurchaseEntry, entry_id)
    if e is None:
        raise HTTPException(404)
    c = e.commencing
    farmers, groups, _ = await _entry_form_data(db, c, False, keep_farmer_id=e.farmer_id)
    fields = lock(entry_fields(farmers, groups), {"farmer_id"})
    ctx = _entry_ctx(
        c, fields, entry_values(e), {}, f"/commencings/entries/{e.id}",
        (f"Edit entry — {e.farmer.name}", f"એન્ટ્રી સુધારો — {e.farmer.name}"), False, "",
    )
    return render_with_csrf(request, csrf, "entry_form_page.html", user=user, **ctx)


@router.post("/{commencing_id}/entries", response_class=HTMLResponse)
async def create_entry(
    request: Request, commencing_id: int, all: int = 0, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    await csrf.validate_csrf(request)
    c = await _get_commencing(db, commencing_id)
    return await _save_entry(request, c, None, bool(all), user, db)


@router.post("/entries/{entry_id}", response_class=HTMLResponse)
async def update_entry(
    request: Request, entry_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    await csrf.validate_csrf(request)
    e = await db.get(PurchaseEntry, entry_id)
    if e is None:
        raise HTTPException(404)
    return await _save_entry(request, e.commencing, e, False, user, db)


async def _save_entry(request: Request, c: Commencing, e: PurchaseEntry | None, show_all: bool, user: User, db: AsyncSession):
    c_id = c.id  # read now: a rollback expires the ORM objects
    farmers, groups, filtered = await _entry_form_data(db, c, show_all, keep_farmer_id=e.farmer_id if e else None)
    fields = entry_fields(farmers, groups)
    raw = await read_form(request)
    if e is not None:
        fields = lock(fields, {"farmer_id"})
        raw["farmer_id"] = str(e.farmer_id)
    heading = (f"Edit entry — {e.farmer.name}", f"એન્ટ્રી સુધારો — {e.farmer.name}") if e else (
        f"Add farmer entry — {c.village}", f"ખેડૂત એન્ટ્રી ઉમેરો — {c.village}")
    action = f"/commencings/entries/{e.id}" if e else f"/commencings/{c_id}/entries" + ("?all=1" if show_all else "")
    ctx_c = SimpleNamespace(id=c_id)  # _entry_ctx only needs the id once the ORM objects may be expired

    def rerender(errs):
        return render(request, "partials/master_form.html", **_entry_ctx(
            ctx_c, fields, raw, errs, action, heading, filtered, f"/commencings/{c_id}/entries/new?all=1"))

    clean, errors = run_validation(EntryIn, fields, normalize_fields(fields, raw))
    if errors:
        return rerender(errors)
    clean["extra_kilos"] = clean["extra_kilos"] or 0
    clean["borrowing"] = clean["borrowing"] or 0
    if clean["extra_kilos"] >= c.net_weight:
        return rerender({"extra_kilos": (f"Must be less than one bag ({c.net_weight} kg); add it to the bag count", f"એક બેગ ({c.net_weight} કિલો) કરતાં ઓછા હોવા જોઈએ")})
    if await db.get(Farmer, clean["farmer_id"]) is None:
        return rerender({"farmer_id": ("Unknown farmer", "અજ્ઞાત ખેડૂત")})
    if await db.get(LabourGroup, clean["labour_group_id"]) is None:
        return rerender({"labour_group_id": ("Unknown labour group", "અજ્ઞાત મજૂર જૂથ")})
    try:
        await assert_year_open(db, clean["entry_date"])
        if e is not None:
            await assert_year_open(db, e.entry_date)
    except YearLockedError as exc:
        return rerender({"entry_date": YEAR_LOCKED(exc.label)})

    new_payable = payable_amount(clean["filled_bags"], clean["extra_kilos"], c.net_weight, c.rate_per_20kg)
    if clean["borrowing"] > new_payable:
        return rerender({"borrowing": (f"Cannot exceed the amount payable (₹{new_payable})", f"ચૂકવવાપાત્ર રકમ (₹{new_payable}) થી વધુ ન હોઈ શકે")})

    before = None
    if e is not None:
        paid = await paid_for_entry(db, e.id)
        if new_payable - clean["borrowing"] < paid:
            return rerender({"filled_bags": (f"₹{paid} is already paid against this entry; the amount cannot go below that", f"આ એન્ટ્રી સામે ₹{paid} ચૂકવાઈ ગયા છે; રકમ તેથી ઓછી ન થઈ શકે")})
        before = entry_snapshot(e)
        for name, value in clean.items():
            setattr(e, name, value)
    else:
        e = PurchaseEntry(commencing_id=c.id, created_by=user.id, **clean)
        db.add(e)
    recalc(e, c)
    await db.flush()
    audit.log(db, user, "update" if before else "create", "purchase_entries", e.id, audit.diff(before, entry_snapshot(e)))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return rerender({"filled_bags": GENERIC_ERROR})
    return Response(status_code=204, headers={"HX-Redirect": f"/commencings/{c_id}"})
