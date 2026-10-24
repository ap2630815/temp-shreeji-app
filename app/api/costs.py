"""Other business costs: labour work (payable, borrowing, petrol, meal) and bag supplies (and bag storage per farmer)."""

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
from app.api.formkit import GENERIC_ERROR, YEAR_LOCKED, form_context, normalize_fields, read_form, toolbar_ids, toolbar_window, today
from app.api.masters_config import F, run_validation
from app.core.db import get_db
from app.core.templating import render, render_with_csrf
from app.models import BagSupplier, BagSupply, Farmer, LabourGroup, LabourWork, User
from app.services import audit
from app.services.payables import load_payables, paid_for
from app.services.years import YearLockedError, allowed_years, assert_year_open, current_year_label

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
    return render_with_csrf(request, csrf, "labour_list.html", user=user, rows=rows, paid=paid, year=year, years=years, year_locked=year != current_year_label())


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
            await assert_year_open(db, w.work_date)
    except YearLockedError as exc:
        return rerender({"work_date": YEAR_LOCKED(exc.label)})
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
    supplier_id: int
    farmer_id: int
    supply_date: date
    rate_per_bag: Annotated[int, Field(gt=0, le=1_000_000)]
    no_of_bags: Annotated[int, Field(gt=0, le=INT_MAX)]
    description: str | None = None


async def bag_fields(db: AsyncSession, village_id: int = 0) -> list[F]:
    suppliers = list((await db.scalars(select(BagSupplier).order_by(BagSupplier.pet_name))).all())
    stmt = select(Farmer).order_by(Farmer.farmer_name)
    if village_id:  # the toolbar village
        stmt = stmt.where(Farmer.village_id == village_id)
    farmers = list((await db.scalars(stmt)).unique().all())
    farmers.sort(key=lambda f: (f.village.village_name, f.farmer_name))
    return [
        F("supplier_id", "Bag supplier", "બારદાન સપ્લાયર", kind="select", required=True, options=tuple((str(s.id), f"{s.pet_name} — {s.name}") for s in suppliers)),
        F("farmer_id", "Delivered at farmer's place", "ખેડૂતને ત્યાં ઉતાર્યું", kind="select", required=True, options=tuple((str(f.id), f"{f.village.village_name} — {f.farmer_name}") for f in farmers),
          help=("The farmer who stores the bags for the village", "જે ખેડૂત ગામ માટે બારદાન સાચવે છે")),
        F("supply_date", "Date", "તારીખ", kind="date", required=True),
        F("rate_per_bag", "Rate per bag (₹)", "બેગ દીઠ ભાવ (₹)", kind="int", required=True),
        F("no_of_bags", "Bags supplied", "આપેલી બેગ", kind="int", required=True),
        F("description", "Description", "વર્ણન", kind="textarea"),
    ]


def bag_values(b: BagSupply) -> dict:
    return dict(supplier_id=str(b.supplier_id), farmer_id=str(b.farmer_id), supply_date=b.supply_date.isoformat(), rate_per_bag=str(b.rate_per_bag), no_of_bags=str(b.no_of_bags), description=b.description or "")


def bag_snapshot(b: BagSupply) -> dict:
    return dict(supplier_id=b.supplier_id, farmer_id=b.farmer_id, supply_date=b.supply_date, rate_per_bag=b.rate_per_bag, no_of_bags=b.no_of_bags, payable_amount=b.payable_amount, description=b.description)


@router.get("/BagSupplies", response_class=HTMLResponse)
async def bag_list(request: Request, year: str = "", view: str = "supplies", village_id: int = 0, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    years = await _years(db, BagSupply, user)
    year = year if year in years else current_year_label()
    stmt = select(BagSupply).where(BagSupply.business_year == year)
    if village_id:  # supplies delivered to a farmer of that village
        stmt = stmt.join(Farmer, Farmer.id == BagSupply.farmer_id).where(Farmer.village_id == village_id)
    if window := toolbar_window(request):
        stmt = stmt.where(BagSupply.supply_date.between(*window))
    rows = list((await db.scalars(stmt.order_by(BagSupply.supply_date.desc(), BagSupply.id.desc()))).unique().all())
    paid = {p.payable_id: p.paid for p in await load_payables(db, "bag_supplier")}
    storage: dict[int, dict] = {}
    for r in rows:  # bags held at each farmer's place for the year
        s = storage.setdefault(r.farmer_id, dict(farmer=r.farmer, units=0, amount=0, suppliers=set()))
        s["units"] += r.no_of_bags
        s["amount"] += r.payable_amount
        s["suppliers"].add(r.supplier.pet_name)
    return render_with_csrf(request, csrf, "bag_list.html", user=user, rows=rows, paid=paid, year=year, years=years, view=view,
                            storage=sorted(storage.values(), key=lambda s: (s["farmer"].village.village_name, s["farmer"].farmer_name)),
                            total_units=sum(r.no_of_bags for r in rows), total_amount=sum(r.payable_amount for r in rows), year_locked=year != current_year_label())


@router.get("/BagSupplies/New", response_class=HTMLResponse)
async def bag_new(request: Request, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    ctx = form_context(fields=await bag_fields(db, toolbar_ids(request)[0]), values=dict(supply_date=today().isoformat()), errors={}, action="/BagSupplies",
                       heading=("Bag supply", "બારદાન સપ્લાય"), back_url="/BagSupplies")
    return render_with_csrf(request, csrf, "master_form_page.html", user=user, **ctx)


@router.get("/BagSupplies/{supply_id}/Edit", response_class=HTMLResponse)
async def bag_edit(request: Request, supply_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    b = await db.get(BagSupply, supply_id)
    if b is None:
        raise HTTPException(404)
    ctx = form_context(fields=await bag_fields(db), values=bag_values(b), errors={}, action=f"/BagSupplies/{b.id}",
                       heading=("Edit bag supply", "બારદાન સપ્લાય સુધારો"), back_url="/BagSupplies")
    return render_with_csrf(request, csrf, "master_form_page.html", user=user, **ctx)


@router.post("/BagSupplies", response_class=HTMLResponse)
async def bag_create(request: Request, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    await csrf.validate_csrf(request)
    return await _save_bag(request, None, user, db)


@router.post("/BagSupplies/{supply_id}", response_class=HTMLResponse)
async def bag_update(request: Request, supply_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    await csrf.validate_csrf(request)
    b = await db.get(BagSupply, supply_id)
    if b is None:
        raise HTTPException(404)
    return await _save_bag(request, b, user, db)


async def _save_bag(request: Request, b: BagSupply | None, user: User, db: AsyncSession):
    b_id = b.id if b else None
    fields = await bag_fields(db)
    raw = await read_form(request)
    action = f"/BagSupplies/{b_id}" if b_id else "/BagSupplies"
    rerender = lambda errs: render(request, "partials/master_form.html", **form_context(  # noqa: E731
        fields=fields, values=raw, errors=errs, action=action, heading=("Bag supply", "બારદાન સપ્લાય"), back_url="/BagSupplies"))
    clean, errors = run_validation(BagIn, fields, normalize_fields(fields, raw))
    if errors:
        return rerender(errors)
    for name, model in (("supplier_id", BagSupplier), ("farmer_id", Farmer)):
        if await db.get(model, clean[name]) is None:
            return rerender({name: ("Unknown value", "અજ્ઞાત કિંમત")})
    try:
        clean["business_year"] = await assert_year_open(db, clean["supply_date"])
        if b is not None:
            await assert_year_open(db, b.supply_date)
    except YearLockedError as exc:
        return rerender({"supply_date": YEAR_LOCKED(exc.label)})
    clean["payable_amount"] = clean["rate_per_bag"] * clean["no_of_bags"]
    before = None
    if b is not None:
        paid = await paid_for(db, "bag_supplier", b.id)
        if clean["payable_amount"] < paid:
            return rerender({"no_of_bags": (f"₹ {paid} is already paid for this supply; the amount cannot go below that", f"આ સપ્લાય માટે ₹ {paid} ચૂકવાઈ ગયા છે; રકમ તેથી ઓછી ન થઈ શકે")})
        before = bag_snapshot(b)
        for name, value in clean.items():
            setattr(b, name, value)
    else:
        b = BagSupply(created_by=user.id, **clean)
        db.add(b)
    await db.flush()
    audit.log(db, user, "update" if before else "create", "bag_supplies", b.id, audit.diff(before, bag_snapshot(b)))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return rerender({"no_of_bags": GENERIC_ERROR})
    return Response(status_code=204, headers={"HX-Redirect": "/BagSupplies"})
