"""Other business costs: labour work (payable, borrowing, petrol, meal) and bag supplies (and bag storage per farmer)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi_csrf_protect import CsrfProtect
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.api.formkit import GENERIC_ERROR, YEAR_LOCKED, form_context, normalize_fields, read_form, toolbar_ids, toolbar_window, today
from app.api.masters_config import F, run_validation
from app.core.db import get_db
from app.core.templating import render, render_with_csrf
from app.models import EmptyBagMoverEntry, EmptyBagSeller, EmptyBagSellerEntry, EmptyBagMover, Farmer, LabourGroup, LabourWork, User
from app.services import audit
from app.services.payables import load_payables, paid_for
from app.services.years import YearLockedError, allowed_years, assert_year_open, current_year_label, assert_year_editable, year_is_locked

router = APIRouter()
INT_MAX = 100_000_000
Money = Annotated[int, Field(ge=0, le=INT_MAX)]


async def _years(db: AsyncSession, model, user: User) -> list[str]:
    return allowed_years(user, (await db.scalars(select(model.business_year).distinct())).all())


# ================================================================== labour work

class LabourIn(BaseModel):
    labour_group_id: int
    work_date: date
    payable_amount: Money | None = None
    borrowing_amount: Money | None = None
    petrol: Money | None = None
    meal: Money | None = None
    description: str | None = None


async def labour_fields(db: AsyncSession) -> list[F]:
    groups = list((await db.scalars(select(LabourGroup).order_by(LabourGroup.group_name))).all())
    return [
        F("labour_group_id", "Labour group", "મજૂર જૂથ", kind="select", required=True, options=tuple((str(g.id), g.group_name) for g in groups)),
        F("work_date", "Date", "તારીખ", kind="date", required=True),
        F("payable_amount", "Wages earned (₹)", "મજૂરી (₹)", kind="int"),
        F("borrowing_amount", "Borrowing to deduct (₹)", "ઉધાર કાપવાના (₹)", kind="int", help=("Taken in advance by the group; deducted from this day's wages", "જૂથે એડવાન્સ લીધેલ; આ દિવસની મજૂરીમાંથી કપાશે")),
        F("petrol", "Petrol (₹) — not deducted", "પેટ્રોલ (₹) — કપાતું નથી", kind="int"),
        F("meal", "Meal (₹) — not deducted", "જમવાનું (₹) — કપાતું નથી", kind="int"),
        F("description", "Description", "વર્ણન", kind="textarea"),
    ]


def labour_values(w: LabourWork) -> dict:
    return dict(labour_group_id=str(w.labour_group_id), work_date=w.work_date.isoformat(), payable_amount=str(w.payable_amount),
                borrowing_amount=str(w.borrowing_amount), petrol=str(w.petrol), meal=str(w.meal), description=w.description or "")


def labour_snapshot(w: LabourWork) -> dict:
    return dict(labour_group_id=w.labour_group_id, work_date=w.work_date, payable_amount=w.payable_amount, borrowing_amount=w.borrowing_amount,
                petrol=w.petrol, meal=w.meal, description=w.description)


@router.get("/LabourWork", response_class=HTMLResponse)
async def labour_list(request: Request, year: str = "", user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    years = await _years(db, LabourWork, user)
    year = year if year in years else current_year_label()
    stmt = select(LabourWork).where(LabourWork.business_year == year)
    if window := toolbar_window(request):
        stmt = stmt.where(LabourWork.work_date.between(*window))
    rows = list((await db.scalars(stmt.order_by(LabourWork.work_date.desc(), LabourWork.id.desc()))).unique().all())
    paid = {p.payable_id: p.paid for p in await load_payables(db, "labour_group")}
    return render_with_csrf(request, csrf, "labour_list.html", user=user, rows=rows, paid=paid, year=year, years=years, year_locked=year_is_locked(user, year))


@router.get("/LabourWork/New", response_class=HTMLResponse)
async def labour_new(request: Request, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    ctx = form_context(fields=await labour_fields(db), values=dict(work_date=today().isoformat(), payable_amount="0", borrowing_amount="0", petrol="0", meal="0"),
                       errors={}, action="/LabourWork", heading=("Labour work", "મજૂર કામ"), back_url="/LabourWork")
    return render_with_csrf(request, csrf, "master_form_page.html", user=user, **ctx)


@router.get("/LabourWork/{work_id}/Edit", response_class=HTMLResponse)
async def labour_edit(request: Request, work_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    w = await db.get(LabourWork, work_id)
    if w is None:
        raise HTTPException(404)
    ctx = form_context(fields=await labour_fields(db), values=labour_values(w), errors={}, action=f"/LabourWork/{w.id}",
                       heading=("Edit labour work", "મજૂર કામ સુધારો"), back_url="/LabourWork")
    return render_with_csrf(request, csrf, "master_form_page.html", user=user, **ctx)


@router.post("/LabourWork", response_class=HTMLResponse)
async def labour_create(request: Request, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    await csrf.validate_csrf(request)
    return await _save_labour(request, None, user, db)


@router.post("/LabourWork/{work_id}", response_class=HTMLResponse)
async def labour_update(request: Request, work_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    await csrf.validate_csrf(request)
    w = await db.get(LabourWork, work_id)
    if w is None:
        raise HTTPException(404)
    return await _save_labour(request, w, user, db)


async def _save_labour(request: Request, w: LabourWork | None, user: User, db: AsyncSession):
    w_id = w.id if w else None
    fields = await labour_fields(db)
    raw = await read_form(request)
    action = f"/LabourWork/{w_id}" if w_id else "/LabourWork"
    rerender = lambda errs: render(request, "partials/master_form.html", **form_context(  # noqa: E731
        fields=fields, values=raw, errors=errs, action=action, heading=("Labour work", "મજૂર કામ"), back_url="/LabourWork"))
    clean, errors = run_validation(LabourIn, fields, normalize_fields(fields, raw))
    if errors:
        return rerender(errors)
    for name in ("payable_amount", "borrowing_amount", "petrol", "meal"):
        clean[name] = clean[name] or 0
    if await db.get(LabourGroup, clean["labour_group_id"]) is None:
        return rerender({"labour_group_id": ("Unknown labour group", "અજ્ઞાત મજૂર જૂથ")})
    if clean["borrowing_amount"] > clean["payable_amount"]:
        return rerender({"borrowing_amount": (f"Cannot exceed the wages (₹ {clean['payable_amount']}); record the rest on another day", f"મજૂરી (₹ {clean['payable_amount']}) થી વધુ ન હોઈ શકે; બાકીનું બીજા દિવસે નોંધો")})
    try:
        clean["business_year"] = await assert_year_open(db, clean["work_date"])
        if w is not None:
            await assert_year_editable(db, w.work_date)
    except YearLockedError as exc:
        return rerender({"work_date": YEAR_LOCKED(exc)})
    before = None
    if w is not None:
        paid = await paid_for(db, "labour_group", w.id)
        net = clean["payable_amount"] - clean["borrowing_amount"]
        if net < paid:
            return rerender({"payable_amount": (f"₹ {paid} is already paid for this day; wages cannot go below that", f"આ દિવસ માટે ₹ {paid} ચૂકવાઈ ગયા છે; મજૂરી તેથી ઓછી ન થઈ શકે")})
        before = labour_snapshot(w)
        for name, value in clean.items():
            setattr(w, name, value)
    else:
        w = LabourWork(created_by=user.id, **clean)
        db.add(w)
    await db.flush()
    audit.log(db, user, "update" if before else "create", "labour_work", w.id, audit.diff(before, labour_snapshot(w)))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return rerender({"payable_amount": GENERIC_ERROR})
    return Response(status_code=204, headers={"HX-Redirect": "/LabourWork"})


# ================================================================== bag supplies

class BagIn(BaseModel):
    empty_bag_seller_id: int
    farmer_id: int
    selling_date: date
    rate_per_bag: Annotated[int, Field(gt=0, le=1_000_000)]
    no_of_empty_bags: Annotated[int, Field(gt=0, le=INT_MAX)]
    description: str | None = None


async def bag_fields(db: AsyncSession, village_id: int = 0) -> list[F]:
    suppliers = list((await db.scalars(select(EmptyBagSeller).order_by(EmptyBagSeller.pet_name))).all())
    stmt = select(Farmer).order_by(Farmer.farmer_name)
    if village_id:  # the toolbar village
        stmt = stmt.where(Farmer.village_id == village_id)
    farmers = list((await db.scalars(stmt)).unique().all())
    farmers.sort(key=lambda f: (f.village.village_name, f.farmer_name))
    return [
        F("empty_bag_seller_id", "Bag supplier", "બારદાન સપ્લાયર", kind="select", required=True, options=tuple((str(s.id), f"{s.pet_name} — {s.name}") for s in suppliers)),
        F("farmer_id", "Delivered at farmer's place", "ખેડૂતને ત્યાં ઉતાર્યું", kind="select", required=True, options=tuple((str(f.id), f"{f.village.village_name} — {f.farmer_name}") for f in farmers),
          help=("The farmer who stores the bags for the village", "જે ખેડૂત ગામ માટે બારદાન સાચવે છે")),
        F("selling_date", "Date", "તારીખ", kind="date", required=True),
        F("rate_per_bag", "Rate per bag (₹)", "બેગ દીઠ ભાવ (₹)", kind="int", required=True),
        F("no_of_empty_bags", "Bags supplied", "આપેલી બેગ", kind="int", required=True),
        F("description", "Description", "વર્ણન", kind="textarea"),
    ]


def bag_values(b: EmptyBagSellerEntry) -> dict:
    return dict(empty_bag_seller_id=str(b.empty_bag_seller_id), farmer_id=str(b.farmer_id), selling_date=b.selling_date.isoformat(), rate_per_bag=str(b.rate_per_bag), no_of_empty_bags=str(b.no_of_empty_bags), description=b.description or "")


def bag_snapshot(b: EmptyBagSellerEntry) -> dict:
    return dict(empty_bag_seller_id=b.empty_bag_seller_id, farmer_id=b.farmer_id, selling_date=b.selling_date, rate_per_bag=b.rate_per_bag, no_of_empty_bags=b.no_of_empty_bags, payable_amount=b.payable_amount, description=b.description)


@router.get("/BagSupplies")
@router.get("/BagSupplies/{rest:path}")
@router.get("/BagSuppliers")
@router.get("/BagSuppliers/{rest:path}")
async def bag_old_url(request: Request, rest: str = ""):
    path = request.url.path.replace("/BagSupplies", "/EmptyBags", 1).replace("/BagSuppliers", "/EmptyBags", 1)
    return RedirectResponse(path + (f"?{request.url.query}" if request.url.query else ""), status_code=307)


@router.get("/EmptyBags", response_class=HTMLResponse)
async def bag_list(request: Request, year: str = "", view: str = "supplies", village_id: int = 0, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    years = sorted(set(await _years(db, EmptyBagSellerEntry, user)) | set(await _years(db, EmptyBagMoverEntry, user)), reverse=True)
    year = year if year in years else current_year_label()
    stmt = select(EmptyBagSellerEntry).where(EmptyBagSellerEntry.business_year == year)
    mstmt = select(EmptyBagMoverEntry).where(EmptyBagMoverEntry.business_year == year)
    if village_id:  # bags delivered to a farmer of that village
        stmt = stmt.join(Farmer, Farmer.id == EmptyBagSellerEntry.farmer_id).where(Farmer.village_id == village_id)
        mstmt = mstmt.join(Farmer, Farmer.id == EmptyBagMoverEntry.farmer_id).where(Farmer.village_id == village_id)
    if window := toolbar_window(request):
        stmt = stmt.where(EmptyBagSellerEntry.selling_date.between(*window))
        mstmt = mstmt.where(EmptyBagMoverEntry.mover_date.between(*window))
    rows = list((await db.scalars(stmt.order_by(EmptyBagSellerEntry.selling_date.desc(), EmptyBagSellerEntry.id.desc()))).unique().all())
    movers = list((await db.scalars(mstmt.order_by(EmptyBagMoverEntry.mover_date.desc(), EmptyBagMoverEntry.id.desc()))).unique().all())
    paid = {p.payable_id: p.paid for p in await load_payables(db, "empty_bag_seller")}
    storage: dict[int, dict] = {}  # empty bags at each farmer's place = bought from sellers + moved from stockyards
    for r in rows:
        s = storage.setdefault(r.farmer_id, dict(farmer=r.farmer, sold=0, moved=0, units=0, amount=0, suppliers=set(), movers=set()))
        s["sold"] += r.no_of_empty_bags
        s["amount"] += r.payable_amount
        s["suppliers"].add(r.supplier.pet_name)
    for m in movers:
        s = storage.setdefault(m.farmer_id, dict(farmer=m.farmer, sold=0, moved=0, units=0, amount=0, suppliers=set(), movers=set()))
        s["moved"] += m.no_of_empty_bags
        s["movers"].add(m.mover.pet_name)
    for s in storage.values():
        s["units"] = s["sold"] + s["moved"]
    if view == "movers":
        total_units, total_amount = sum(m.no_of_empty_bags for m in movers), sum(m.cost_per_mover for m in movers)
    elif view == "storage":
        total_units, total_amount = sum(s["units"] for s in storage.values()), sum(r.payable_amount for r in rows) + sum(m.cost_per_mover for m in movers)
    else:
        total_units, total_amount = sum(r.no_of_empty_bags for r in rows), sum(r.payable_amount for r in rows)
    return render_with_csrf(request, csrf, "bag_list.html", user=user, rows=rows, movers=movers, paid=paid, year=year, years=years, view=view,
                            storage=sorted(storage.values(), key=lambda s: (s["farmer"].village.village_name, s["farmer"].farmer_name)),
                            total_units=total_units, total_amount=total_amount, year_locked=year_is_locked(user, year))


# ---- movers tab: empty bags carried from a stockyard to a farmer's house (a business cost)

class MoverIn(BaseModel):
    empty_bag_mover_id: int
    farmer_id: int
    mover_date: date
    cost_per_mover: Annotated[int, Field(gt=0, le=1_000_000)]
    no_of_empty_bags: Annotated[int, Field(gt=0, le=INT_MAX)]
    description: str | None = None


async def mover_fields(db: AsyncSession, village_id: int = 0) -> list[F]:
    movers = list((await db.scalars(select(EmptyBagMover).order_by(EmptyBagMover.pet_name))).all())
    base = await bag_fields(db, village_id)
    farmer_f = next(f for f in base if f.name == "farmer_id")
    return [
        F("empty_bag_mover_id", "Empty bag mover", "ખાલી બારદાન મૂવર", kind="select", required=True, options=tuple((str(m.id), f"{m.pet_name} — {m.name}") for m in movers)),
        farmer_f,
        F("mover_date", "Date", "તારીખ", kind="date", required=True),
        F("cost_per_mover", "Cost of the move (₹)", "મૂવરનો ખર્ચ (₹)", kind="int", required=True),
        F("no_of_empty_bags", "Empty bags moved", "ખસેડેલી ખાલી બેગ", kind="int", required=True),
        F("description", "Description", "વર્ણન", kind="textarea"),
    ]


def mover_values(m: EmptyBagMoverEntry) -> dict:
    return dict(empty_bag_mover_id=str(m.empty_bag_mover_id), farmer_id=str(m.farmer_id), mover_date=m.mover_date.isoformat(), cost_per_mover=str(m.cost_per_mover),
                no_of_empty_bags=str(m.no_of_empty_bags), description=m.description or "")


@router.get("/EmptyBags/Movers/New", response_class=HTMLResponse)
async def mover_new(request: Request, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    ctx = form_context(fields=await mover_fields(db, toolbar_ids(request)[0]), values=dict(mover_date=today().isoformat()), errors={}, action="/EmptyBags/Movers",
                       heading=("Empty bag move", "ખાલી બારદાન ખસેડવું"), back_url="/EmptyBags?view=movers")
    return render_with_csrf(request, csrf, "master_form_page.html", user=user, **ctx)


@router.get("/EmptyBags/Movers/{entry_id}/Edit", response_class=HTMLResponse)
async def mover_edit(request: Request, entry_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    m = await db.get(EmptyBagMoverEntry, entry_id)
    if m is None:
        raise HTTPException(404)
    ctx = form_context(fields=await mover_fields(db), values=mover_values(m), errors={}, action=f"/EmptyBags/Movers/{m.id}",
                       heading=("Edit empty bag move", "ખાલી બારદાન ખસેડવું સુધારો"), back_url="/EmptyBags?view=movers")
    return render_with_csrf(request, csrf, "master_form_page.html", user=user, **ctx)


@router.post("/EmptyBags/Movers", response_class=HTMLResponse)
async def mover_create(request: Request, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    await csrf.validate_csrf(request)
    return await _save_mover(request, None, user, db)


@router.post("/EmptyBags/Movers/{entry_id}", response_class=HTMLResponse)
async def mover_update(request: Request, entry_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    await csrf.validate_csrf(request)
    m = await db.get(EmptyBagMoverEntry, entry_id)
    if m is None:
        raise HTTPException(404)
    return await _save_mover(request, m, user, db)


async def _save_mover(request: Request, m: EmptyBagMoverEntry | None, user: User, db: AsyncSession):
    raw = await read_form(request)
    fields = await mover_fields(db)
    action = f"/EmptyBags/Movers/{m.id}" if m else "/EmptyBags/Movers"
    rerender = lambda errs: render(request, "master_form_page.html", user=user, **form_context(
        fields=fields, values=raw, errors=errs, action=action, heading=("Empty bag move", "ખાલી બારદાન ખસેડવું"), back_url="/EmptyBags?view=movers"))
    clean, errors = run_validation(MoverIn, fields, normalize_fields(fields, raw))
    if errors:
        return rerender(errors)
    for name, model in (("empty_bag_mover_id", EmptyBagMover), ("farmer_id", Farmer)):
        if await db.get(model, clean[name]) is None:
            return rerender({name: ("Unknown value", "અજ્ઞાત કિંમત")})
    try:
        clean["business_year"] = await assert_year_open(db, clean["mover_date"])
        if m is not None:
            await assert_year_editable(db, m.mover_date)
    except YearLockedError as exc:
        return rerender({"mover_date": YEAR_LOCKED(exc)})
    before = None
    if m is not None:
        before = mover_values(m)
        for name, value in clean.items():
            setattr(m, name, value)
    else:
        m = EmptyBagMoverEntry(created_by=user.id, **clean)
        db.add(m)
    await db.flush()
    audit.log(db, user, "update" if before else "create", "empty_bag_movers_entries", m.id, audit.diff(before, mover_values(m)))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return rerender({"no_of_empty_bags": GENERIC_ERROR})
    return Response(status_code=204, headers={"HX-Redirect": "/EmptyBags?view=movers"})


@router.get("/EmptyBags/New", response_class=HTMLResponse)
async def bag_new(request: Request, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    ctx = form_context(fields=await bag_fields(db, toolbar_ids(request)[0]), values=dict(selling_date=today().isoformat()), errors={}, action="/EmptyBags",
                       heading=("Bag supply", "બારદાન સપ્લાય"), back_url="/EmptyBags")
    return render_with_csrf(request, csrf, "master_form_page.html", user=user, **ctx)


@router.get("/EmptyBags/{supply_id}/Edit", response_class=HTMLResponse)
async def bag_edit(request: Request, supply_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    b = await db.get(EmptyBagSellerEntry, supply_id)
    if b is None:
        raise HTTPException(404)
    ctx = form_context(fields=await bag_fields(db), values=bag_values(b), errors={}, action=f"/EmptyBags/{b.id}",
                       heading=("Edit bag supply", "બારદાન સપ્લાય સુધારો"), back_url="/EmptyBags")
    return render_with_csrf(request, csrf, "master_form_page.html", user=user, **ctx)


@router.post("/EmptyBags", response_class=HTMLResponse)
async def bag_create(request: Request, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    await csrf.validate_csrf(request)
    return await _save_bag(request, None, user, db)


@router.post("/EmptyBags/{supply_id}", response_class=HTMLResponse)
async def bag_update(request: Request, supply_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    await csrf.validate_csrf(request)
    b = await db.get(EmptyBagSellerEntry, supply_id)
    if b is None:
        raise HTTPException(404)
    return await _save_bag(request, b, user, db)


async def _save_bag(request: Request, b: EmptyBagSellerEntry | None, user: User, db: AsyncSession):
    b_id = b.id if b else None
    fields = await bag_fields(db)
    raw = await read_form(request)
    action = f"/EmptyBags/{b_id}" if b_id else "/EmptyBags"
    rerender = lambda errs: render(request, "partials/master_form.html", **form_context(  # noqa: E731
        fields=fields, values=raw, errors=errs, action=action, heading=("Bag supply", "બારદાન સપ્લાય"), back_url="/EmptyBags"))
    clean, errors = run_validation(BagIn, fields, normalize_fields(fields, raw))
    if errors:
        return rerender(errors)
    for name, model in (("empty_bag_seller_id", EmptyBagSeller), ("farmer_id", Farmer)):
        if await db.get(model, clean[name]) is None:
            return rerender({name: ("Unknown value", "અજ્ઞાત કિંમત")})
    try:
        clean["business_year"] = await assert_year_open(db, clean["selling_date"])
        if b is not None:
            await assert_year_editable(db, b.selling_date)
    except YearLockedError as exc:
        return rerender({"selling_date": YEAR_LOCKED(exc)})
    clean["payable_amount"] = clean["rate_per_bag"] * clean["no_of_empty_bags"]
    before = None
    if b is not None:
        paid = await paid_for(db, "empty_bag_seller", b.id)
        if clean["payable_amount"] < paid:
            return rerender({"no_of_empty_bags": (f"₹ {paid} is already paid for this supply; the amount cannot go below that", f"આ સપ્લાય માટે ₹ {paid} ચૂકવાઈ ગયા છે; રકમ તેથી ઓછી ન થઈ શકે")})
        before = bag_snapshot(b)
        for name, value in clean.items():
            setattr(b, name, value)
    else:
        b = EmptyBagSellerEntry(created_by=user.id, **clean)
        db.add(b)
    await db.flush()
    audit.log(db, user, "update" if before else "create", "empty_bag_sellers_entries", b.id, audit.diff(before, bag_snapshot(b)))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return rerender({"no_of_empty_bags": GENERIC_ERROR})
    return Response(status_code=204, headers={"HX-Redirect": "/EmptyBags"})
