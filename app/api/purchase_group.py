"""Purchase group (one deal with the few farmers who gathered in a village) and the farmer entries inside it.

A village has many purchase_group over time. The owner lists the farmers taking part (purchase_group_farmers); each listed
farmer gets his own ledger of entries in that deal."""

from datetime import date, timedelta
from types import SimpleNamespace
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi_csrf_protect import CsrfProtect
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.api.formkit import GENERIC_ERROR, YEAR_LOCKED, apply_toolbar, form_context, lock, normalize_fields, read_form, toolbar_ids, today
from app.api.masters_config import F, national_mobile, run_validation
from app.core.db import get_db
from app.core.templating import format_mobile, render, render_with_csrf
from app.models import Farmer, Grain, LabourGroup, PurchaseFarmerEntry, PurchaseGroup, PurchaseGroupFarmer, TruckLoadLine, User, Village
from app.services import audit, roster
from app.services.ledger import entry_views, paid_for_entry, purchase_group_entries, totals
from app.services.money import payable_amount, total_available_bags
from app.services.stock import renumber_remaining
from app.services.years import YearLockedError, allowed_years, assert_year_open, business_year_of, current_year_label, require_year_visible

router = APIRouter(prefix="/PurchaseGroup")

INT_MAX = 100_000_000


# ---------------------------------------------------------------- purchase_group forms

class PurchaseGroupIn(BaseModel):
    purchase_group_date: date
    village_id: int
    grain_id: int
    grain_rate_per_20kg: Annotated[int, Field(gt=0, le=1_000_000)]
    pay_after_no_of_days: Annotated[int, Field(ge=0, le=3650)]
    purchase_group_terms: str | None = None
    description: str | None = None


def purchase_group_fields(villages: list[Village], grains: list[Grain]) -> list[F]:
    return [
        F("purchase_group_date", "Date", "તારીખ", kind="date", required=True),
        F("village_id", "Village", "ગામ", kind="select", required=True, options=tuple((str(v.id), v.village_name) for v in villages)),
        F("grain_id", "Grain", "અનાજ", kind="select", required=True,
          options=tuple((str(g.id), f"{g.grain_name} / {g.grain_name_gu or ''} — {g.net_bag_weight} kg bag") for g in grains)),
        F("grain_rate_per_20kg", "Rate per 20 kg (₹)", "20 કિલો દીઠ ભાવ (₹)", kind="int", required=True),
        F("pay_after_no_of_days", "Pay after (days)", "ચુકવણી (દિવસ પછી)", kind="int", required=True),
        F("purchase_group_terms", "Terms & conditions", "શરતો", kind="textarea",
          help=("Leave blank to copy the grain's default terms", "ખાલી રાખો તો અનાજની ડિફોલ્ટ શરતો લેવાશે")),
        F("description", "Description", "વર્ણન", kind="textarea"),
    ]


def purchase_group_values(p: PurchaseGroup) -> dict:
    return dict(
        purchase_group_date=p.purchase_group_date.isoformat(), village_id=str(p.village_id), grain_id=str(p.grain_id),
        grain_rate_per_20kg=str(p.grain_rate_per_20kg), pay_after_no_of_days=str(p.pay_after_no_of_days),
        purchase_group_terms=p.purchase_group_terms or "", description=p.description or "",
    )


def purchase_group_snapshot(p: PurchaseGroup) -> dict:
    return dict(
        purchase_group_date=p.purchase_group_date, village_id=p.village_id, grain_id=p.grain_id, grain_rate_per_20kg=p.grain_rate_per_20kg,
        pay_after_no_of_days=p.pay_after_no_of_days, purchase_group_terms=p.purchase_group_terms, description=p.description,
    )


async def _masters(db: AsyncSession) -> tuple[list[Village], list[Grain]]:
    villages = list((await db.scalars(select(Village).order_by(Village.village_name))).all())
    grains = list((await db.scalars(select(Grain).order_by(Grain.grain_name))).all())
    return villages, grains


# ---------------------------------------------------------------- entry forms

class EntryIn(BaseModel):
    farmer_id: int
    labour_group_id: int
    purchase_entry_date: date
    no_of_filled_bags: Annotated[int, Field(ge=0, le=INT_MAX)]
    extra_kilos: Annotated[int, Field(ge=0, le=INT_MAX)] | None = None  # blank means 0
    no_of_handful_bags: Annotated[int, Field(ge=0, le=INT_MAX)] | None = None  # blank means 0
    expected_raw_weight_per_bag: Annotated[int, Field(ge=0, le=INT_MAX)] | None = None
    grain_quality_code: str | None = None
    grain_store_at: str | None = None
    borrowed_amount: Annotated[int, Field(ge=0, le=INT_MAX)] | None = None  # blank means 0
    description: str | None = None


def entry_fields(farmers: list[Farmer], groups: list[LabourGroup]) -> list[F]:
    return [
        F("farmer_id", "Farmer", "ખેડૂત", kind="select", required=True,
          options=tuple((str(f.id), f"{f.farmer_name} — {f.village.village_name} — {format_mobile(f.mobile)}") for f in farmers)),
        F("labour_group_id", "Labour group", "મજૂર જૂથ", kind="select", required=True,
          options=tuple((str(g.id), g.group_name) for g in groups)),
        F("purchase_entry_date", "Date", "તારીખ", kind="date", required=True),
        F("no_of_filled_bags", "Filled bags", "ભરેલી બેગ", kind="int", required=True),
        F("extra_kilos", "Extra kilos (loose, beyond full bags)", "વધારાના કિલો (પૂરી બેગ ઉપરાંત)", kind="int"),
        F("no_of_handful_bags", "Handful bags", "હેન્ડફુલ બેગ", kind="int",
          help=("Counted in the stock, not in the payment", "સ્ટોકમાં ગણાય છે, ચુકવણીમાં નહીં")),
        F("expected_raw_weight_per_bag", "Expected raw weight per bag (kg) — reference only", "બેગ દીઠ અપેક્ષિત કાચું વજન (કિલો) — ફક્ત સંદર્ભ",
          kind="int", help=("Used only to compare with the weighbridge, never in the payment", "ફક્ત કાંટા સાથે સરખામણી માટે, ચુકવણીમાં ક્યારેય નહીં")),
        F("grain_quality_code", "Grain quality code", "અનાજ ગુણવત્તા કોડ"),
        F("grain_store_at", "Grain stored at", "અનાજ ક્યાં સંગ્રહ્યું"),
        F("borrowed_amount", "Borrowing / advance to deduct (₹)", "ઉધાર / એડવાન્સ કાપવાના (₹)", kind="int"),
        F("description", "Description (e.g. 2 quality grains, warning)", "વર્ણન (દા.ત. બે ગુણવત્તા, ચેતવણી)", kind="textarea"),
    ]


def entry_values(e: PurchaseFarmerEntry) -> dict:
    n = lambda v: "" if v is None else str(v)  # noqa: E731
    return dict(
        farmer_id=str(e.farmer_id), labour_group_id=str(e.labour_group_id), purchase_entry_date=e.purchase_entry_date.isoformat(),
        no_of_filled_bags=str(e.no_of_filled_bags), extra_kilos=str(e.extra_kilos), no_of_handful_bags=str(e.no_of_handful_bags),
        expected_raw_weight_per_bag=n(e.expected_raw_weight_per_bag), grain_quality_code=e.grain_quality_code or "",
        grain_store_at=e.grain_store_at or "", borrowed_amount=str(e.borrowed_amount), description=e.description or "",
    )


def entry_snapshot(e: PurchaseFarmerEntry) -> dict:
    return dict(
        farmer_id=e.farmer_id, labour_group_id=e.labour_group_id, purchase_entry_date=e.purchase_entry_date, no_of_filled_bags=e.no_of_filled_bags,
        extra_kilos=e.extra_kilos, no_of_handful_bags=e.no_of_handful_bags, total_available_bags=e.total_available_bags,
        expected_raw_weight_per_bag=e.expected_raw_weight_per_bag, grain_quality_code=e.grain_quality_code, grain_store_at=e.grain_store_at,
        borrowed_amount=e.borrowed_amount, payable_amount=e.payable_amount, due_date=e.due_date, description=e.description,
    )


def recalc(entry: PurchaseFarmerEntry, info: PurchaseGroup) -> None:
    """Rate, bag weight and pay-after always come from the purchase_group and its grain; entries cannot override them."""
    entry.payable_amount = payable_amount(entry.no_of_filled_bags, entry.extra_kilos, info.grain.net_bag_weight, info.grain_rate_per_20kg)
    entry.due_date = entry.purchase_entry_date + timedelta(days=info.pay_after_no_of_days)
    entry.total_available_bags = total_available_bags(entry.no_of_filled_bags, entry.no_of_handful_bags)


async def _get_info(db: AsyncSession, purchase_group_id: int) -> PurchaseGroup:
    p = await db.get(PurchaseGroup, purchase_group_id)
    if p is None:
        raise HTTPException(404)
    return p


async def _years_with_data(db: AsyncSession, user: User) -> list[str]:
    return allowed_years(user, (await db.scalars(select(PurchaseGroup.business_year).distinct())).all())


# ---------------------------------------------------------------- list

@router.get("", response_class=HTMLResponse)
async def list_page(
    request: Request, year: str = "", grain_id: int = 0, village_id: int = 0, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    years = await _years_with_data(db, user)
    year = year if year in years else current_year_label()
    stmt = select(PurchaseGroup).where(PurchaseGroup.business_year == year)
    if grain_id:
        stmt = stmt.where(PurchaseGroup.grain_id == grain_id)
    if village_id:
        stmt = stmt.where(PurchaseGroup.village_id == village_id)
    infos = (await db.scalars(stmt.order_by(PurchaseGroup.purchase_group_date.desc(), PurchaseGroup.id.desc()))).unique().all()
    views = await entry_views(db, purchase_group_ids=[p.id for p in infos]) if infos else []
    per: dict[int, list] = {p.id: [] for p in infos}
    for v in views:
        per[v.entry.purchase_group_id].append(v)
    listed: dict[int, int] = {}
    if infos:
        listed = {pid: int(n) for pid, n in (await db.execute(
            select(PurchaseGroupFarmer.purchase_group_id, func.count()).where(PurchaseGroupFarmer.purchase_group_id.in_([p.id for p in infos])).group_by(PurchaseGroupFarmer.purchase_group_id)
        )).all()}
    now = today()
    rows = [(p, totals(per[p.id], now), listed.get(p.id, 0)) for p in infos]
    return render_with_csrf(
        request, csrf, "purchase_group_list.html", user=user, rows=rows, grain_id=grain_id, year=year, years=years, year_locked=year != current_year_label()
    )


# ---------------------------------------------------------------- the purchase form: fields on the left, farmer picker on the right

def _ints(values) -> list[int]:
    out: list[int] = []
    for v in values:
        if str(v).isdigit() and int(v) not in out:
            out.append(int(v))
    return out


async def _farmers_by_id(db: AsyncSession, ids: list[int]) -> list[Farmer]:
    if not ids:
        return []
    by_id = {f.id: f for f in (await db.scalars(select(Farmer).where(Farmer.id.in_(ids)))).unique().all()}
    return [by_id[i] for i in ids if i in by_id]


async def _form_page_ctx(db: AsyncSession, p_id: int | None, fields, values, errors, selected: list[Farmer], *, modal=None, confirm_dupes=False) -> dict:
    villages, _ = await _masters(db)
    heading = ("Edit purchase", "ખરીદી સુધારો") if p_id else ("New purchase", "નવી ખરીદી")
    return form_context(
        fields=fields, values=values, errors=errors, action=f"/PurchaseGroup/{p_id}" if p_id else "/PurchaseGroup", heading=heading,
        back_url=f"/PurchaseGroup/{p_id}" if p_id else "/PurchaseGroup", selected=selected, picker_villages=villages, picker_village=values.get("village_id", ""),
        p_id=p_id, modal=modal, confirm_dupes=confirm_dupes, year=current_year_label(), picker_grain=values.get("grain_id", ""),
        picker_free=("pfree" in values) if "pfree_seen" in values else True,  # ticked by default; a form sent back keeps the user's choice
    )


@router.get("/New", response_class=HTMLResponse)
async def new_page(request: Request, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    villages, grains = await _masters(db)
    values = apply_toolbar(request, dict(purchase_group_date=today().isoformat()))
    ctx = await _form_page_ctx(db, None, purchase_group_fields(villages, grains), values, {}, [])
    return render_with_csrf(request, csrf, "purchase_group_form_page.html", user=user, **ctx)


@router.get("/FarmerSearch", response_class=HTMLResponse)
async def farmer_search(
    request: Request, pv: str = "", pq: str = "", pfree: str = "", pinfo: str = "", pg: str = "", user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    """The picker's results: existing farmers narrowed by village / name / mobile. Farmers already in another purchase of the
    selected grain this year are tagged; `pfree` hides them.
    (Plain strings: an empty filter arrives as an empty value.)"""
    stmt = select(Farmer).join(Village, Village.id == Farmer.village_id).order_by(Village.village_name, Farmer.farmer_name).limit(60)
    if pv.isdigit():
        stmt = stmt.where(Farmer.village_id == int(pv))
    q = pq.strip()
    if q:
        like = f"%{q}%"
        digits = national_mobile(q) if any(ch.isdigit() for ch in q) else ""  # 98765 43210 / +91 98765 43210 find 9876543210
        stmt = stmt.where(or_(Farmer.farmer_name.ilike(like), Farmer.farmer_name_gu.ilike(like), Farmer.mobile.ilike(like), Farmer.head_of_family.ilike(like),
                              *([Farmer.mobile.ilike(f"%{digits}%")] if digits else [])))
    farmers = list((await db.scalars(stmt)).unique().all())
    deals = await roster.other_deals(db, [f.id for f in farmers], int(pg), current_year_label(), int(pinfo) if pinfo.isdigit() else None) if pg.isdigit() else {}
    if pfree:
        farmers = [f for f in farmers if f.id not in deals]
    return render(request, "partials/farmer_results.html", farmers=farmers, deals=deals)


@router.get("/{purchase_group_id}/Edit", response_class=HTMLResponse)
async def edit_page(
    request: Request, purchase_group_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    p = await _get_info(db, purchase_group_id)
    villages, grains = await _masters(db)
    fields = lock(purchase_group_fields(villages, grains), await _locked_info_fields(db, p, user))
    selected = await _farmers_by_id(db, await roster.listed_farmer_ids(db, p.id))
    ctx = await _form_page_ctx(db, p.id, fields, apply_toolbar(request, purchase_group_values(p)), {}, selected)
    return render_with_csrf(request, csrf, "purchase_group_form_page.html", user=user, **ctx)


async def _locked_info_fields(db: AsyncSession, p: PurchaseGroup, user: User) -> set[str]:
    has_entries = bool(await db.scalar(select(func.count()).select_from(PurchaseFarmerEntry).where(PurchaseFarmerEntry.purchase_group_id == p.id)))
    locked: set[str] = set()
    if has_entries:
        locked |= {"grain_id", "purchase_group_date", "village_id"}  # entries depend on all three
        if user.role != "owner":
            locked |= {"grain_rate_per_20kg", "pay_after_no_of_days"}  # only the owner may reprice
    return locked


@router.post("", response_class=HTMLResponse)
async def create_info(
    request: Request, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    await csrf.validate_csrf(request)
    return await _save_info(request, None, user, db)


@router.post("/{purchase_group_id}", response_class=HTMLResponse)
async def update_info(
    request: Request, purchase_group_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    await csrf.validate_csrf(request)
    return await _save_info(request, purchase_group_id, user, db)


async def _save_info(request: Request, purchase_group_id: int | None, user: User, db: AsyncSession):
    user_id, role = user.id, user.role  # read now: a rollback expires `user`
    form = await request.form()
    raw = {k: v for k, v in form.items() if isinstance(v, str)}
    picked = _ints(form.getlist("farmer_ids"))
    confirm_dupes = raw.get("confirm_dupes") == "1"
    villages, grains = await _masters(db)
    p = await _get_info(db, purchase_group_id) if purchase_group_id else None
    p_id = p.id if p else None  # read now: a rollback expires `p`
    fields = purchase_group_fields(villages, grains)
    locked: set[str] = set()
    if p is not None:
        locked = await _locked_info_fields(db, p, user)
        stored = purchase_group_values(p)
        raw.update({name: stored[name] for name in locked})  # locked fields keep their stored value
    fields = lock(fields, locked)
    selected = await _farmers_by_id(db, picked)

    async def rerender(errs, modal=None):
        ctx = await _form_page_ctx(db, p_id, fields, raw, errs, selected, modal=modal, confirm_dupes=confirm_dupes)
        return render(request, "partials/purchase_group_form.html", **ctx)

    clean, errors = run_validation(PurchaseGroupIn, fields, normalize_fields(fields, raw))
    if len(selected) != len(picked):
        errors["farmer_ids"] = ("Unknown farmer", "અજ્ઞાત ખેડૂત")
    elif p is None and not picked:
        errors["farmer_ids"] = ("Pick at least one farmer who joined this purchase", "આ ખરીદીમાં જોડાયેલ ઓછામાં ઓછો એક ખેડૂત પસંદ કરો")
    if errors:
        return await rerender(errors)

    grain = await db.get(Grain, clean["grain_id"])
    if grain is None:
        return await rerender({"grain_id": ("Unknown grain", "અજ્ઞાત અનાજ")})
    if await db.get(Village, clean["village_id"]) is None:
        return await rerender({"village_id": ("Unknown village", "અજ્ઞાત ગામ")})
    clean["purchase_group_terms"] = clean["purchase_group_terms"] or grain.grain_terms
    try:
        clean["business_year"] = await assert_year_open(db, clean["purchase_group_date"])
        if p is not None:  # also the stored year must be open, otherwise a locked year could be edited
            await assert_year_open(db, p.purchase_group_date)
    except YearLockedError as exc:
        return await rerender({"purchase_group_date": YEAR_LOCKED(exc.label)})

    listed = await roster.listed_farmer_ids(db, p_id) if p_id else []
    added = [f for f in picked if f not in listed]
    removed = [f for f in listed if f not in picked]

    # a farmer already in another purchase of the same grain this business year: the owner must verify before he is listed again
    if added and not confirm_dupes:
        deals = await roster.other_deals(db, added, clean["grain_id"], clean["business_year"], p_id)
        if deals:
            names = {f.id: f for f in selected}
            return await rerender({}, modal=dict(kind="dupes", rows=[(names[fid], infos) for fid, infos in deals.items()]))

    # a farmer taken off the list loses his ledger entries here, unless a later step already used them
    gone_entries = await roster.entries_of(db, p_id, removed) if removed else []
    stuck = await roster.in_use(db, gone_entries)
    if stuck:
        names = ", ".join(f.farmer_name for f in stuck)
        return await rerender({"farmer_ids": (f"Cannot remove {names}: his entries are already loaded on a truck or paid",
                                              f"{names} ને કાઢી શકાતા નથી: તેમની નોંધ ટ્રકમાં ભરાઈ ગઈ છે અથવા ચૂકવણી થઈ ગઈ છે")})

    before = purchase_group_snapshot(p) if p else None
    if p is None:
        p = PurchaseGroup(created_by=user_id, **clean)
        db.add(p)
        await db.flush()
    else:
        for name, value in clean.items():
            setattr(p, name, value)
    if removed:
        await roster.remove_farmers(db, user, p.id, removed, gone_entries)
    for fid in added:
        db.add(PurchaseGroupFarmer(purchase_group_id=p.id, farmer_id=fid, created_by=user_id))
        audit.log(db, user, "create", "purchase_group_farmers", None, dict(purchase_group_id=p.id, farmer_id=fid))
    await db.flush()
    if before is not None:
        problem = await _reprice_entries(db, p)
        if problem:
            await db.rollback()
            return await rerender({"grain_rate_per_20kg": problem})
    audit.log(db, user, "update" if before else "create", "purchase_group", p.id, audit.diff(before, purchase_group_snapshot(p)))
    new_id = p.id
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return await rerender({"village_id": GENERIC_ERROR})
    return Response(status_code=204, headers={"HX-Redirect": f"/PurchaseGroup/{new_id}"})


async def _reprice_entries(db: AsyncSession, p: PurchaseGroup) -> tuple[str, str] | None:
    """Re-derive every entry after a rate / pay-after change; refuse if it would drop below what is already paid."""
    for view in await purchase_group_entries(db, p.id):
        e = view.entry
        recalc(e, p)
        if e.borrowed_amount > e.payable_amount or e.net_payable < view.paid:
            return (
                f"This change would take {e.farmer.farmer_name}'s amount below what is already paid / borrowed",
                f"આ ફેરફારથી {e.farmer.farmer_name}ની રકમ ચૂકવેલી / ઉધાર રકમથી ઓછી થશે",
            )
    return None


# ---------------------------------------------------------------- detail

@router.get("/{purchase_group_id}", response_class=HTMLResponse)
async def detail_page(
    request: Request, purchase_group_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    p = await _get_info(db, purchase_group_id)
    require_year_visible(user, p.business_year)
    views = await purchase_group_entries(db, p.id)
    now = today()
    per: dict[int, list] = {}
    for v in views:
        per.setdefault(v.entry.farmer_id, []).append(v)
    farmers = await _farmers_by_id(db, await roster.listed_farmer_ids(db, p.id))
    people = [dict(farmer=f, entries=len(per.get(f.id, [])), totals=totals(per.get(f.id, []), now)) for f in farmers]
    return render_with_csrf(request, csrf, "purchase_group_detail.html", user=user, p=p, views=views, totals=totals(views, now), today=now, people=people)


# ---------------------------------------------------------------- entries (a listed farmer's ledger in this deal)

async def _entry_form_data(db: AsyncSession, p: PurchaseGroup):
    """Only the farmers listed on this purchase_group can have entries in it."""
    farmers = await _farmers_by_id(db, await roster.listed_farmer_ids(db, p.id))
    farmers.sort(key=lambda f: f.farmer_name)
    groups = list((await db.scalars(select(LabourGroup).order_by(LabourGroup.group_name))).all())
    return farmers, groups


def _entry_ctx(p, fields, values, errors, action, heading, has_farmers=True):
    return form_context(
        fields=fields, values=values, errors=errors, action=action, heading=heading, back_url=f"/PurchaseGroup/{p.id}", p=p, has_farmers=has_farmers,
    )


@router.get("/{purchase_group_id}/Entries/New", response_class=HTMLResponse)
async def new_entry_page(
    request: Request, purchase_group_id: int, farmer_id: int = 0, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    p = await _get_info(db, purchase_group_id)
    farmers, groups = await _entry_form_data(db, p)
    ctx = _entry_ctx(
        p, entry_fields(farmers, groups),
        dict(purchase_entry_date=today().isoformat(), extra_kilos="0", no_of_handful_bags="0", borrowed_amount="0", farmer_id=str(farmer_id) if farmer_id else ""), {},
        f"/PurchaseGroup/{p.id}/Entries",
        (f"Add farmer entry — {p.village.village_name}", f"ખેડૂત એન્ટ્રી ઉમેરો — {p.village.village_name}"), bool(farmers),
    )
    return render_with_csrf(request, csrf, "entry_form_page.html", user=user, **ctx)


@router.get("/Entries/{entry_id}/Edit", response_class=HTMLResponse)
async def edit_entry_page(
    request: Request, entry_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    e = await db.get(PurchaseFarmerEntry, entry_id)
    if e is None:
        raise HTTPException(404)
    p = e.purchase_group
    farmers, groups = await _entry_form_data(db, p)
    fields = lock(entry_fields(farmers, groups), {"farmer_id"})
    ctx = _entry_ctx(
        p, fields, entry_values(e), {}, f"/PurchaseGroup/Entries/{e.id}",
        (f"Edit entry — {e.farmer.farmer_name}", f"એન્ટ્રી સુધારો — {e.farmer.farmer_name}"),
    )
    return render_with_csrf(request, csrf, "entry_form_page.html", user=user, **ctx)


@router.post("/{purchase_group_id}/Entries", response_class=HTMLResponse)
async def create_entry(
    request: Request, purchase_group_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    await csrf.validate_csrf(request)
    p = await _get_info(db, purchase_group_id)
    return await _save_entry(request, p, None, user, db)


@router.post("/Entries/{entry_id}", response_class=HTMLResponse)
async def update_entry(
    request: Request, entry_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)
):
    await csrf.validate_csrf(request)
    e = await db.get(PurchaseFarmerEntry, entry_id)
    if e is None:
        raise HTTPException(404)
    return await _save_entry(request, e.purchase_group, e, user, db)


async def _save_entry(request: Request, p: PurchaseGroup, e: PurchaseFarmerEntry | None, user: User, db: AsyncSession):
    p_id, village_name, net_weight = p.id, p.village.village_name, p.grain.net_bag_weight  # read now: a rollback expires the ORM objects
    farmers, groups = await _entry_form_data(db, p)
    fields = entry_fields(farmers, groups)
    raw = await read_form(request)
    if e is not None:
        fields = lock(fields, {"farmer_id"})
        raw["farmer_id"] = str(e.farmer_id)
    heading = (f"Edit entry — {e.farmer.farmer_name}", f"એન્ટ્રી સુધારો — {e.farmer.farmer_name}") if e else (
        f"Add farmer entry — {village_name}", f"ખેડૂત એન્ટ્રી ઉમેરો — {village_name}")
    action = f"/PurchaseGroup/Entries/{e.id}" if e else f"/PurchaseGroup/{p_id}/Entries"
    ctx_p = SimpleNamespace(id=p_id, village=SimpleNamespace(village_name=village_name), grain=p.grain,
                            grain_rate_per_20kg=p.grain_rate_per_20kg, pay_after_no_of_days=p.pay_after_no_of_days)

    def rerender(errs):
        return render(request, "partials/master_form.html", **_entry_ctx(ctx_p, fields, raw, errs, action, heading))

    clean, errors = run_validation(EntryIn, fields, normalize_fields(fields, raw))
    if errors:
        return rerender(errors)
    clean["extra_kilos"] = clean["extra_kilos"] or 0
    clean["no_of_handful_bags"] = clean["no_of_handful_bags"] or 0
    clean["borrowed_amount"] = clean["borrowed_amount"] or 0
    if clean["extra_kilos"] >= net_weight:
        return rerender({"extra_kilos": (f"Must be less than one bag ({net_weight} kg); add it to the bag count", f"એક બેગ ({net_weight} કિલો) કરતાં ઓછા હોવા જોઈએ")})
    if clean["farmer_id"] not in {f.id for f in farmers}:
        return rerender({"farmer_id": ("This farmer is not listed on this purchase; add him by editing the purchase", "આ ખેડૂત આ ખરીદીમાં નથી; ખરીદી સુધારીને ઉમેરો")})
    if await db.get(LabourGroup, clean["labour_group_id"]) is None:
        return rerender({"labour_group_id": ("Unknown labour group", "અજ્ઞાત મજૂર જૂથ")})
    try:
        await assert_year_open(db, clean["purchase_entry_date"])
        if e is not None:
            await assert_year_open(db, e.purchase_entry_date)
    except YearLockedError as exc:
        return rerender({"purchase_entry_date": YEAR_LOCKED(exc.label)})
    clean["business_year"] = await assert_year_open(db, clean["purchase_entry_date"])

    new_payable = payable_amount(clean["no_of_filled_bags"], clean["extra_kilos"], net_weight, p.grain_rate_per_20kg)
    if clean["borrowed_amount"] > new_payable:
        return rerender({"borrowed_amount": (f"Cannot exceed the amount payable (₹ {new_payable})", f"ચૂકવવાપાત્ર રકમ (₹ {new_payable}) થી વધુ ન હોઈ શકે")})

    before = None
    if e is not None:
        paid = await paid_for_entry(db, e.id)
        if new_payable - clean["borrowed_amount"] < paid:
            return rerender({"no_of_filled_bags": (f"₹ {paid} is already paid against this entry; the amount cannot go below that", f"આ એન્ટ્રી સામે ₹ {paid} ચૂકવાઈ ગયા છે; રકમ તેથી ઓછી ન થઈ શકે")})
        loaded = int(await db.scalar(select(func.coalesce(func.sum(TruckLoadLine.no_of_loaded_bags), 0)).where(TruckLoadLine.purchase_farmer_entry_id == e.id)))
        available = total_available_bags(clean["no_of_filled_bags"], clean["no_of_handful_bags"])
        if available < loaded:
            return rerender({"no_of_filled_bags": (f"{loaded} bags of this entry are already loaded on trucks; the total cannot go below that", f"આ એન્ટ્રીની {loaded} બેગ ટ્રકમાં ભરાઈ ગઈ છે; કુલ તેથી ઓછી ન થઈ શકે")})
        before = entry_snapshot(e)
        for name, value in clean.items():
            setattr(e, name, value)
    else:
        e = PurchaseFarmerEntry(purchase_group_id=p_id, created_by=user.id, **clean)
        db.add(e)
    recalc(e, p)
    await db.flush()
    if before is not None:
        await renumber_remaining(db, e.id)
    audit.log(db, user, "update" if before else "create", "purchase_farmers_entries", e.id, audit.diff(before, entry_snapshot(e)))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return rerender({"no_of_filled_bags": GENERIC_ERROR})
    return Response(status_code=204, headers={"HX-Redirect": f"/PurchaseGroup/{p_id}"})
