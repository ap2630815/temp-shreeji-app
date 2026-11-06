"""The farmer ledger screens.

/PurchaseFarmers          tabs (like /StockyardPurchase; bags = the farmer bag ledger): entries = every farmer ledger entry of the business year (purchase and direct\n                          entries together), groups = the purchase groups (deals), individuals = the direct entries
/PurchaseIndividual       direct entries (+ add / + edit): ONE form holding the purchase columns (date, village, grain, rate,
                          pay-after, terms) and the entry columns (farmer, labour group, bags, amounts...) with ONE description.
                          One flat row per farmer entry in purchase_individuals, no purchase_group.

A direct entry is part of the farmer ledger: it is paid through the normal farmer payments (allocations of type
'purchase_individual'), and shows up in payables, statements, the year report and the farmer analysis next to the purchase entries."""

from dataclasses import replace
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi_csrf_protect import CsrfProtect
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.api.formkit import GENERIC_ERROR, YEAR_LOCKED, apply_toolbar, form_context, lock, normalize_fields, read_form, toolbar_ids, toolbar_window, today
from app.api.masters_config import F, run_validation
from app.core.db import get_db
from app.core.templating import format_mobile, render, render_with_csrf
from app.models import PurchaseIndividual, Farmer, Grain, LabourGroup, PurchaseFarmerEntry, User, Village
from app.services import audit
from app.services.duplicates import DUPLICATE_MSG, find_duplicate
from app.services.locations import stored_locations
from app.services.stock import Stock, stock_by_entry
from app.services.ledger import all_entry_views, direct_entry_views, paid_for_direct, totals
from app.services.money import payable_amount, total_available_bags
from app.services.years import YearLockedError, allowed_years, assert_year_open, current_year_label

router = APIRouter()
INT_MAX = 100_000_000


# ---------------------------------------------------------------- the ledger lists

async def _years(db: AsyncSession, user: User) -> list[str]:
    found: set[str] = set()
    for model in (PurchaseFarmerEntry, PurchaseIndividual):
        found |= set((await db.scalars(select(model.business_year).distinct())).all())
    return allowed_years(user, found)


VIEWS = ("entries", "groups", "individuals", "bags")


async def farmer_bag_rows(db: AsyncSession, year: str, village_id: int = 0, grain_id: int = 0) -> list[dict]:
    """The farmer bag ledger of the year: purchase group entries and purchase individuals side by side."""
    group = list((await db.scalars(select(PurchaseFarmerEntry).where(PurchaseFarmerEntry.business_year == year)
                                   .order_by(PurchaseFarmerEntry.purchase_entry_date.desc(), PurchaseFarmerEntry.id.desc()))).unique().all())
    direct = list((await db.scalars(select(PurchaseIndividual).where(PurchaseIndividual.business_year == year)
                                    .order_by(PurchaseIndividual.purchase_individual_date.desc(), PurchaseIndividual.id.desc()))).unique().all())
    group = [e for e in group if (not village_id or e.purchase_group.village_id == village_id) and (not grain_id or e.purchase_group.grain_id == grain_id)]
    direct = [e for e in direct if (not village_id or e.village_id == village_id) and (not grain_id or e.grain_id == grain_id)]
    g_stock = await stock_by_entry(db, [e.id for e in group]) if group else {}
    d_stock = await stock_by_entry(db, [e.id for e in direct], individual=True) if direct else {}
    rows = [dict(kind="PurchaseGroup", link=f"/PurchaseGroup/{e.purchase_group_id}", entry=e, stock=g_stock[e.id]) for e in group]
    rows += [dict(kind="PurchaseIndividual", link="/PurchaseIndividual", entry=e, stock=d_stock[e.id]) for e in direct]
    return sorted(rows, key=lambda r: (r["entry"].entry_date, r["entry"].id), reverse=True)


async def _ledger_page(request, csrf, db, user, *, view, year, grain_id, village_id):
    from app.api.purchase_group import group_rows  # imported late: purchase_group is the other farmer-ledger module

    years = sorted(set(await _years(db, user)) | set(await _group_years(db, user)), reverse=True)
    year = year if year in years else current_year_label()
    now = today()
    ctx = dict(view=view, today=now, year=year, years=years, year_locked=year != current_year_label(), views=[], totals=None, rows=[])
    if view == "groups":
        ctx["rows"] = await group_rows(db, year, grain_id, village_id, toolbar_window(request))
        return render_with_csrf(request, csrf, "farmers_entries.html", user=user, **ctx)
    if view == "bags":  # bags bought / loaded on trucks / taken to a stockyard / still at the farmer, per entry
        ctx["rows"] = await farmer_bag_rows(db, year, village_id, grain_id)
        return render_with_csrf(request, csrf, "farmers_entries.html", user=user, **ctx)
    source = direct_entry_views(db) if view == "individuals" else all_entry_views(db)
    views = [v for v in await source if v.entry.business_year == year and (not grain_id or v.entry.grain.id == grain_id) and (not village_id or v.entry.farmer.village_id == village_id)]  # the village of the farmer; a purchase's own village is reached through its # link
    if window := toolbar_window(request):
        views = [v for v in views if window[0] <= v.entry.entry_date <= window[1]]
    views.sort(key=lambda v: (v.entry.entry_date, v.entry.id), reverse=True)
    ctx.update(views=views, totals=totals(views, now))
    return render_with_csrf(request, csrf, "farmers_entries.html", user=user, **ctx)


async def _group_years(db: AsyncSession, user: User) -> list[str]:
    from app.models import PurchaseGroup

    return allowed_years(user, (await db.scalars(select(PurchaseGroup.business_year).distinct())).all())


@router.get("/PurchaseFarmers", response_class=HTMLResponse)
async def farmers_page(
    request: Request, view: str = "entries", year: str = "", grain_id: int = 0, village_id: int = 0, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    return await _ledger_page(request, csrf, db, user, view=view if view in VIEWS else "entries", year=year, grain_id=grain_id, village_id=village_id)


@router.get("/PurchaseFarmersEntries")
async def old_all_entries_url(request: Request):
    q = request.url.query
    return RedirectResponse("/PurchaseFarmers" + (f"?{q}" if q else ""), status_code=307)


@router.get("/PurchaseIndividual")
async def direct_list(request: Request, user: User = Depends(current_user)):
    """The direct entries are the 'individuals' tab of /PurchaseFarmers."""
    q = request.url.query
    return RedirectResponse("/PurchaseFarmers?view=individuals" + (f"&{q}" if q else ""), status_code=307)


# ---------------------------------------------------------------- the one form

class PurchaseIndividualIn(BaseModel):
    purchase_individual_date: date
    village_id: int
    grain_id: int
    grain_rate_per_20kg: Annotated[int, Field(gt=0, le=1_000_000)]
    pay_after_no_of_days: Annotated[int, Field(ge=0, le=3650)]
    terms: str | None = None
    farmer_id: int
    labour_group_id: int
    no_of_filled_bags: Annotated[int, Field(ge=0, le=INT_MAX)]
    extra_kilos: Annotated[int, Field(ge=0, le=INT_MAX)] | None = None  # blank means 0
    no_of_handful_bags: Annotated[int, Field(ge=0, le=INT_MAX)] | None = None  # blank means 0
    expected_raw_weight_per_bag: Annotated[float, Field(ge=0, le=1000)] | None = None  # blank: the grain's value
    grain_quality_code: str | None = None
    grain_stored_location: str | None = None
    borrowed_amount: Annotated[int, Field(ge=0, le=INT_MAX)] | None = None  # blank means 0
    description: str | None = None


async def direct_fields(db: AsyncSession) -> tuple[list[F], list[F], dict[int, int], dict[int, int]]:
    """(the purchase columns, the entry columns, grain id -> kg per bag, farmer id -> his village id). The description is the last field of the entry part: one for both."""
    villages = list((await db.scalars(select(Village).order_by(Village.village_name))).all())
    grains = list((await db.scalars(select(Grain).order_by(Grain.grain_name))).all())
    farmers = list((await db.scalars(select(Farmer).order_by(Farmer.farmer_name))).unique().all())
    groups = list((await db.scalars(select(LabourGroup).order_by(LabourGroup.group_name))).all())
    purchase = [
        F("purchase_individual_date", "Date", "તારીખ", kind="date", required=True),
        F("village_id", "Village", "ગામ", kind="select", required=True, options=tuple((str(v.id), v.village_name) for v in villages)),
        F("grain_id", "Grain", "અનાજ", kind="select", required=True,
          options=tuple((str(g.id), f"{g.grain_name} / {g.grain_name_gu or ''} — {g.net_bag_weight} kg bag") for g in grains)),
        F("grain_rate_per_20kg", "Rate per 20 kg (₹)", "20 કિલો દીઠ ભાવ (₹)", kind="int", required=True),
        F("pay_after_no_of_days", "Pay after (days)", "ચુકવણી (દિવસ પછી)", kind="int", required=True),
        F("terms", "Terms & conditions", "શરતો", kind="textarea", help=("Leave blank to copy the grain's default terms", "ખાલી રાખો તો અનાજની ડિફોલ્ટ શરતો લેવાશે")),
    ]
    entry = [
        F("farmer_id", "Farmer", "ખેડૂત", kind="select", required=True, options=tuple((str(f.id), f"{f.farmer_name} — {f.village.village_name} — {format_mobile(f.mobile)}") for f in farmers)),
        F("labour_group_id", "Labour group", "મજૂર જૂથ", kind="select", required=True, options=tuple((str(g.id), g.group_name) for g in groups)),
        F("no_of_filled_bags", "Filled bags", "ભરેલી બેગ", kind="int", required=True),
        F("extra_kilos", "Extra kilos (loose, beyond full bags)", "વધારાના કિલો (પૂરી બેગ ઉપરાંત)", kind="int"),
        F("no_of_handful_bags", "Handful bags", "હેન્ડફુલ બેગ", kind="int", help=("Counted in the stock, not in the payment", "સ્ટોકમાં ગણાય છે, ચુકવણીમાં નહીં")),
        F("expected_raw_weight_per_bag", "Expected raw weight per bag (kg)", "બેગ દીઠ અપેક્ષિત કાચું વજન (કિલો)", kind="decimal",
          help=("Used only to compare with the weighbridge, never in the payment. Blank starts at the grain's value", "ફક્ત કાંટા સાથે સરખામણી માટે, ચુકવણીમાં ક્યારેય નહીં. ખાલી રાખો તો અનાજના મૂલ્યથી શરૂ")),
        F("grain_quality_code", "Grain quality code", "અનાજ ગુણવત્તા કોડ"),
        F("grain_stored_location", "Grain stored location", "અનાજ સંગ્રહ સ્થળ", options=await stored_locations(db),
          help=("Pick a place used before, or type a new one (text in brackets is ignored when matching)", "પહેલાં વપરાયેલ સ્થળ પસંદ કરો અથવા નવું લખો (કૌંસનો લખાણ ગણાતું નથી)")),
        F("borrowed_amount", "Borrowing / advance to deduct (₹)", "ઉધાર / એડવાન્સ કાપવાના (₹)", kind="int"),
        F("description", "Description", "વર્ણન", kind="textarea"),
    ]
    return purchase, entry, {g.id: g.net_bag_weight for g in grains}, {f.id: f.village_id for f in farmers}


def direct_values(e: PurchaseIndividual) -> dict:
    n = lambda v: "" if v is None else str(v)  # noqa: E731
    return dict(
        purchase_individual_date=e.purchase_individual_date.isoformat(), village_id=str(e.village_id), grain_id=str(e.grain_id), grain_rate_per_20kg=str(e.grain_rate_per_20kg),
        pay_after_no_of_days=str(e.pay_after_no_of_days), terms=e.terms or "", farmer_id=str(e.farmer_id), labour_group_id=str(e.labour_group_id),
        no_of_filled_bags=str(e.no_of_filled_bags), extra_kilos=str(e.extra_kilos), no_of_handful_bags=str(e.no_of_handful_bags),
        expected_raw_weight_per_bag=f"{e.expected_raw_weight_per_bag:g}", grain_quality_code=e.grain_quality_code or "", grain_stored_location=e.grain_stored_location or "",
        borrowed_amount=str(e.borrowed_amount), description=e.description or "",
    )


def direct_snapshot(e: PurchaseIndividual) -> dict:
    return dict(
        purchase_individual_date=e.purchase_individual_date, village_id=e.village_id, grain_id=e.grain_id, grain_rate_per_20kg=e.grain_rate_per_20kg, pay_after_no_of_days=e.pay_after_no_of_days,
        farmer_id=e.farmer_id, labour_group_id=e.labour_group_id, no_of_filled_bags=e.no_of_filled_bags, extra_kilos=e.extra_kilos, no_of_handful_bags=e.no_of_handful_bags,
        total_available_bags=e.total_available_bags, expected_raw_weight_per_bag=e.expected_raw_weight_per_bag, borrowed_amount=e.borrowed_amount,
        payable_amount=e.payable_amount, due_date=e.due_date, description=e.description,
    )


async def _get_direct(db: AsyncSession, entry_id: int) -> PurchaseIndividual:
    e = await db.get(PurchaseIndividual, entry_id)
    if e is None:
        raise HTTPException(404)
    return e


def _ctx(purchase_fields, entry_fields, values, errors, action, heading, nets, editing, farmer_villages):
    return form_context(
        fields=purchase_fields + entry_fields, purchase_fields=purchase_fields, entry_fields=entry_fields, values=values, errors=errors, action=action,
        heading=heading, back_url="/PurchaseFarmers?view=individuals", nets=nets, editing=editing, farmer_villages=farmer_villages,
    )


@router.get("/PurchaseIndividual/New", response_class=HTMLResponse)
async def direct_new(request: Request, like: int = 0, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    purchase, entry, nets, farmer_villages = await direct_fields(db)
    values = dict(purchase_individual_date=today().isoformat(), extra_kilos="0", no_of_handful_bags="0", borrowed_amount="0")
    if like:  # "Save & add another": keep the purchase columns of the previous entry, start the entry columns afresh
        prev = await db.get(PurchaseIndividual, like)
        if prev is not None:
            values.update({k: v for k, v in direct_values(prev).items() if k in {f.name for f in purchase}})
    values = apply_toolbar(request, values)  # the toolbar village / grain start their fields (editable)
    village_id = toolbar_ids(request)[0]
    if village_id:  # and the farmers of that village
        entry = [replace(f, options=tuple(o for o in f.options if farmer_villages.get(int(o[0])) == village_id)) if f.name == "farmer_id" else f for f in entry]
    ctx = _ctx(purchase, entry, values, {}, "/PurchaseFarmers?view=individuals", ("Add purchase individual", "ખરીદી વ્યક્તિગત ઉમેરો"), nets, False, farmer_villages)
    return render_with_csrf(request, csrf, "direct_form_page.html", user=user, **ctx)


@router.get("/PurchaseIndividual/{entry_id}/Edit", response_class=HTMLResponse)
async def direct_edit(request: Request, entry_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    e = await _get_direct(db, entry_id)
    purchase, entry, nets, farmer_villages = await direct_fields(db)
    locked = {"farmer_id"} if await paid_for_direct(db, e.id) else set()  # money already paid to this farmer is tied to him
    ctx = _ctx(purchase, lock(entry, locked), apply_toolbar(request, direct_values(e)), {}, f"/PurchaseIndividual/{e.id}",
               (f"Edit direct entry — {e.farmer.farmer_name}", f"સીધી નોંધ સુધારો — {e.farmer.farmer_name}"), nets, True, farmer_villages)
    return render_with_csrf(request, csrf, "direct_form_page.html", user=user, **ctx)


@router.post("/PurchaseIndividual", response_class=HTMLResponse)
async def direct_create(request: Request, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    await csrf.validate_csrf(request)
    return await _save_direct(request, None, user, db)


@router.post("/PurchaseIndividual/{entry_id}", response_class=HTMLResponse)
async def direct_update(request: Request, entry_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    await csrf.validate_csrf(request)
    return await _save_direct(request, await _get_direct(db, entry_id), user, db)


async def _save_direct(request: Request, e: PurchaseIndividual | None, user: User, db: AsyncSession):
    user_id = user.id  # read now: a rollback expires `user` and `e`
    e_id = e.id if e else None
    purchase, entry, nets, farmer_villages = await direct_fields(db)
    raw = await read_form(request)
    again = raw.pop("again", "") == "1"  # the "Save & add another" button
    paid = await paid_for_direct(db, e.id) if e is not None else 0
    locked = {"farmer_id"} if paid else set()
    if e is not None:
        raw.update({name: direct_values(e)[name] for name in locked})
    entry = lock(entry, locked)
    action = f"/PurchaseIndividual/{e_id}" if e_id else "/PurchaseIndividual"
    heading = ("Edit purchase individual", "ખરીદી વ્યક્તિગત સુધારો") if e else ("Add purchase individual", "ખરીદી વ્યક્તિગત ઉમેરો")

    def rerender(errs):
        return render(request, "partials/direct_form.html", **_ctx(purchase, entry, raw, errs, action, heading, nets, e_id is not None, farmer_villages))

    fields = purchase + entry
    clean, errors = run_validation(PurchaseIndividualIn, fields, normalize_fields(fields, raw))
    if errors:
        return rerender(errors)
    for name in ("extra_kilos", "no_of_handful_bags", "borrowed_amount"):
        clean[name] = clean[name] or 0
    village, grain = await db.get(Village, clean["village_id"]), await db.get(Grain, clean["grain_id"])
    if village is None:
        return rerender({"village_id": ("Unknown village", "અજ્ઞાત ગામ")})
    if grain is None:
        return rerender({"grain_id": ("Unknown grain", "અજ્ઞાત અનાજ")})
    for name, model in (("farmer_id", Farmer), ("labour_group_id", LabourGroup)):
        if await db.get(model, clean[name]) is None:
            return rerender({name: ("Unknown value", "અજ્ઞાત કિંમત")})
    if farmer_villages.get(clean["farmer_id"]) != clean["village_id"]:  # the farmer list only offers the selected village's farmers
        return rerender({"farmer_id": (f"This farmer is not from {village.village_name}; pick a {village.village_name} farmer or change the village",
                                       f"આ ખેડૂત {village.village_name} નો નથી; {village.village_name} નો ખેડૂત પસંદ કરો અથવા ગામ બદલો")})
    if clean["expected_raw_weight_per_bag"] is None:  # starts at the grain's value, editable
        clean["expected_raw_weight_per_bag"] = grain.expected_raw_weight_per_bag
    if clean["extra_kilos"] >= grain.net_bag_weight:
        return rerender({"extra_kilos": (f"Must be less than one bag ({grain.net_bag_weight} kg); add it to the bag count", f"એક બેગ ({grain.net_bag_weight} કિલો) કરતાં ઓછા હોવા જોઈએ")})
    try:
        clean["business_year"] = await assert_year_open(db, clean["purchase_individual_date"])
        if e is not None:
            await assert_year_open(db, e.purchase_individual_date)
    except YearLockedError as exc:
        return rerender({"purchase_individual_date": YEAR_LOCKED(exc.label)})

    clean["terms"] = clean["terms"] or grain.grain_terms
    clean["payable_amount"] = payable_amount(clean["no_of_filled_bags"], clean["extra_kilos"], grain.net_bag_weight, clean["grain_rate_per_20kg"])
    clean["due_date"] = clean["purchase_individual_date"] + timedelta(days=clean["pay_after_no_of_days"])
    clean["total_available_bags"] = total_available_bags(clean["no_of_filled_bags"], clean["no_of_handful_bags"])
    if clean["borrowed_amount"] > clean["payable_amount"]:
        return rerender({"borrowed_amount": (f"Cannot exceed the amount payable (₹ {clean['payable_amount']})", f"ચૂકવવાપાત્ર રકમ (₹ {clean['payable_amount']}) થી વધુ ન હોઈ શકે")})
    if clean["payable_amount"] - clean["borrowed_amount"] < paid:
        return rerender({"no_of_filled_bags": (f"₹ {paid} is already paid against this entry; the amount cannot go below that", f"આ એન્ટ્રી સામે ₹ {paid} ચૂકવાઈ ગયા છે; રકમ તેથી ઓછી ન થઈ શકે")})

    if (dup := await find_duplicate(db, clean["farmer_id"], clean["purchase_individual_date"], clean["grain_id"], clean["grain_rate_per_20kg"],
                                    clean["no_of_filled_bags"], clean["extra_kilos"], ("purchase_individuals", e.id) if e else None)):
        return rerender({"no_of_filled_bags": DUPLICATE_MSG(dup)})
    if e is not None:
        stock = (await stock_by_entry(db, [e.id], individual=True)).get(e.id, Stock())
        used = stock.loaded + stock.moved
        if clean["total_available_bags"] < used:
            return rerender({"no_of_filled_bags": (f"{used} bags of this entry are already loaded on trucks or taken to a stockyard; the total cannot go below that",
                                                   f"આ એન્ટ્રીની {used} બેગ ટ્રકમાં ભરાઈ કે સ્ટોકયાર્ડમાં લઈ જવાઈ ગઈ છે; કુલ તેથી ઓછી ન થઈ શકે")})
    before = None
    if e is not None:
        before = direct_snapshot(e)
        for name, value in clean.items():
            setattr(e, name, value)
    else:
        e = PurchaseIndividual(created_by=user_id, **clean)
        db.add(e)
    await db.flush()
    audit.log(db, user, "update" if before else "create", "purchase_individuals", e.id, audit.diff(before, direct_snapshot(e)))
    new_id = e.id
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return rerender({"no_of_filled_bags": GENERIC_ERROR})
    return Response(status_code=204, headers={"HX-Redirect": f"/PurchaseIndividual/New?like={new_id}" if again else "/PurchaseFarmers?view=individuals"})
