"""Stockyard purchases (file4-transactional.txt, /StockyardPurchase): the deal, its weighed entries and the bag arrangement work.

One page with three tabs; every tab lists its records and has its own Add / Edit form with Save and Back."""

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi_csrf_protect import CsrfProtect
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import current_user
from app.api.formkit import GENERIC_ERROR, YEAR_LOCKED, apply_toolbar, form_context, normalize_fields, read_form, toolbar_ids, toolbar_window, today
from app.api.masters_config import F, run_validation
from app.core.db import get_db
from app.core.templating import render, render_with_csrf
from app.models import (
    Farmer,
    FarmerStockyardTransfer,
    Grain,
    LabourGroup,
    PurchaseFarmerEntry,
    PurchaseGroup,
    PurchaseIndividual,
    Stockyard,
    EmptyBag,
    EmptyBagMover,
    EmptyBagSeller,
    Industry,
    StockyardArrangementEntry,
    StockyardPurchase,
    StockyardPurchaseEntry,
    User,
)
from app.services import audit
from app.services.duplicates import DUPLICATE_MSG, find_duplicate
from app.services.locks import advisory_lock
from app.services.money import payable_amount
from app.services.stock import stock_by_entry
from app.services.payables import paid_for, paid_map
from app.services.stockyard_stock import Empty, Filled, default_received, empty_ledger, filled_ledger
from app.services.years import YearLockedError, allowed_years, assert_year_open, current_year_label, assert_year_editable, year_is_locked

router = APIRouter(prefix="/StockyardPurchase")
INT_MAX = 100_000_000
Money = Annotated[int, Field(ge=0, le=INT_MAX)]
TABS = ("purchases", "entries", "arrangements", "transfers", "empty_bags", "stock")
FORM_TABS = ("purchases", "entries", "arrangements", "transfers", "empty_bags")  # the others are read-only ledgers
TAB_MODELS = {"purchases": StockyardPurchase, "entries": StockyardPurchaseEntry, "arrangements": StockyardArrangementEntry,
              "transfers": FarmerStockyardTransfer, "empty_bags": EmptyBag}
HEADINGS = {
    "purchases": (("Stockyard purchase", "સ્ટોકયાર્ડ ખરીદી"), ("Edit stockyard purchase", "સ્ટોકયાર્ડ ખરીદી સુધારો")),
    "entries": (("Stockyard purchase entry", "સ્ટોકયાર્ડ ખરીદી નોંધ"), ("Edit stockyard purchase entry", "સ્ટોકયાર્ડ ખરીદી નોંધ સુધારો")),
    "arrangements": (("Stockyard arrangement entry", "સ્ટોકયાર્ડ ગોઠવણી નોંધ"), ("Edit stockyard arrangement entry", "સ્ટોકયાર્ડ ગોઠવણી નોંધ સુધારો")),
    "transfers": (("Farmer to stockyard", "ખેડૂતથી સ્ટોકયાર્ડ"), ("Edit farmer to stockyard", "ખેડૂતથી સ્ટોકયાર્ડ સુધારો")),
    "empty_bags": (("Empty bags", "ખાલી બેગ"), ("Edit empty bags", "ખાલી બેગ સુધારો")),
}


def _tab(kind: str) -> str:
    if kind not in FORM_TABS:
        raise HTTPException(404)
    return kind


def _back(kind: str) -> str:
    return f"/StockyardPurchase?view={kind}"


def _opt(rows, label) -> tuple[tuple[str, str], ...]:
    return tuple((str(r.id), label(r)) for r in rows)


async def _years(db: AsyncSession, model, user: User) -> list[str]:
    return allowed_years(user, (await db.scalars(select(model.business_year).distinct())).all())


# ================================================================== list (the three tabs)

@router.get("", response_class=HTMLResponse)
async def stockyard_list(request: Request, view: str = "purchases", year: str = "", user: User = Depends(current_user),
                         csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    if view == "farmer_bags":  # moved to the Purchase Farmers page
        q = request.url.query.replace("view=farmer_bags", "view=bags")
        return RedirectResponse(f"/PurchaseFarmers?{q}", status_code=307)
    view = view if view in TABS else "purchases"
    village_id, grain_id = toolbar_ids(request)  # the toolbar's village (the farmer's) and grain
    if view == "stock":  # the stockyards' filled / empty bag ledgers: balances so far, not a year's records (grain only: a stockyard has no village)
        return render_with_csrf(request, csrf, "stockyard_list.html", user=user, view=view, rows=[], year="", years=[], year_locked=False,
                                **await _stock_context(db, grain_id))
    model = TAB_MODELS.get(view, PurchaseFarmerEntry)
    years = await _years(db, model, user)
    year = year if year in years else current_year_label()
    date_col = {"purchases": StockyardPurchase.stockyard_purchase_date, "entries": StockyardPurchaseEntry.stockyard_purchase_entry_date,
                "arrangements": StockyardArrangementEntry.stockyard_arrangement_date, "transfers": FarmerStockyardTransfer.transfer_date,
                "empty_bags": EmptyBag.empty_bags_entry_date}[view]
    stmt = select(model).where(model.business_year == year)
    if window := toolbar_window(request):
        stmt = stmt.where(date_col.between(*window))
    stmt = _toolbar_filter(stmt, view, village_id, grain_id)
    rows = list((await db.scalars(stmt.order_by(date_col.desc(), model.id.desc()))).unique().all())
    extra = dict(bag_paid=await paid_map(db, "empty_bag", [r.id for r in rows])) if view == "empty_bags" else {}
    return render_with_csrf(request, csrf, "stockyard_list.html", user=user, view=view, rows=rows, year=year, years=years,
                            year_locked=year_is_locked(user, year), **extra)


def _toolbar_filter(stmt, view: str, village_id: int, grain_id: int):
    """Village = the farmer's village (for transfers: the village of the farmer entry); grain = the grain of the purchase / entry / movement.
    Rows with no farmer or no grain behind them (arrangements without an entry) drop out while that filter is on."""
    if view == "purchases":
        if village_id:
            stmt = stmt.where(StockyardPurchase.farmer_id.in_(select(Farmer.id).where(Farmer.village_id == village_id)))
        if grain_id:
            stmt = stmt.where(StockyardPurchase.grain_id == grain_id)
    elif view in ("entries", "arrangements"):
        entry_col = StockyardPurchaseEntry.id if view == "entries" else StockyardArrangementEntry.stockyard_purchase_entry_id
        buys = select(StockyardPurchase.id)
        if village_id:
            buys = buys.where(StockyardPurchase.farmer_id.in_(select(Farmer.id).where(Farmer.village_id == village_id)))
        if grain_id:
            buys = buys.where(StockyardPurchase.grain_id == grain_id)
        if village_id or grain_id:
            entries = select(StockyardPurchaseEntry.id).where(StockyardPurchaseEntry.stockyard_purchase_id.in_(buys))
            stmt = stmt.where(entry_col.in_(entries))
    elif view == "transfers":
        if village_id:
            stmt = stmt.where(FarmerStockyardTransfer.purchase_farmer_entry_id.in_(
                select(PurchaseFarmerEntry.id).join(PurchaseGroup, PurchaseGroup.id == PurchaseFarmerEntry.purchase_group_id).where(PurchaseGroup.village_id == village_id))
                | FarmerStockyardTransfer.purchase_individual_id.in_(select(PurchaseIndividual.id).where(PurchaseIndividual.village_id == village_id)))
        if grain_id:
            stmt = stmt.where(FarmerStockyardTransfer.purchase_farmer_entry_id.in_(
                select(PurchaseFarmerEntry.id).join(PurchaseGroup, PurchaseGroup.id == PurchaseFarmerEntry.purchase_group_id).where(PurchaseGroup.grain_id == grain_id))
                | FarmerStockyardTransfer.purchase_individual_id.in_(select(PurchaseIndividual.id).where(PurchaseIndividual.grain_id == grain_id)))
    elif view == "empty_bags":  # no farmer behind these rows: the village filter does not apply (the toolbar freezes it)
        if grain_id:
            stmt = stmt.where(EmptyBag.grain_id == grain_id)
    return stmt


async def _stock_context(db: AsyncSession, grain_id: int = 0) -> dict:
    """One row per stockyard and grain: filled bags (bought here + brought from farmers - loaded) and empty bags (bought - used by purchase entries)."""
    filled, empty = await filled_ledger(db), await empty_ledger(db)
    yards = {y.id: y for y in (await db.scalars(select(Stockyard))).all()}
    grains = {g.id: g for g in (await db.scalars(select(Grain))).all()}
    keys = sorted((k for k in set(filled) | set(empty) if not grain_id or k[1] == grain_id), key=lambda k: (yards[k[0]].name_of_stockyard, grains[k[1]].grain_name))
    return dict(stock_rows=[(yards[sy], grains[gr], filled.get((sy, gr), Filled()), empty.get((sy, gr), Empty())) for sy, gr in keys])


# ================================================================== forms

async def purchase_fields(db: AsyncSession, village_id: int = 0, grain_id: int = 0) -> list[F]:
    yards = list((await db.scalars(select(Stockyard).order_by(Stockyard.name_of_stockyard))).all())
    farmers = list((await db.scalars(select(Farmer).order_by(Farmer.farmer_name))).unique().all())
    if village_id:  # the toolbar village: only its farmers are offered
        farmers = [f for f in farmers if f.village_id == village_id]
    farmers.sort(key=lambda f: (f.village.village_name, f.farmer_name))
    grains = list((await db.scalars(select(Grain).order_by(Grain.grain_name))).all())
    return [
        F("stockyard_purchase_date", "Date", "તારીખ", kind="date", required=True),
        F("stockyard_id", "Stockyard", "સ્ટોકયાર્ડ", kind="select", required=True, options=_opt(yards, lambda y: f"{y.name_of_stockyard} — {y.location}")),
        F("farmer_id", "Farmer", "ખેડૂત", kind="select", required=True, options=_opt(farmers, lambda f: f"{f.village.village_name} — {f.farmer_name}")),
        F("grain_id", "Grain", "અનાજ", kind="select", required=True, options=_opt(grains, lambda g: g.grain_name)),
        F("grain_rate_per_20kg", "Grain rate per 20 kg (₹)", "અનાજનો ભાવ 20 કિલો દીઠ (₹)", kind="int", required=True),
        F("pay_after_no_of_days", "Pay after (days)", "ચુકવણી (દિવસ પછી)", kind="int", required=True),
        F("no_of_given_empty_bags", "Empty bags given", "આપેલી ખાલી બેગ", kind="int",
          help=("Handed to the farmer to fill; what comes back is recorded on each purchase entry", "ખેડૂતને ભરવા આપેલી; પાછી આવેલી દરેક ખરીદી નોંધમાં લખાય છે")),
        F("terms", "Terms & conditions", "શરતો", kind="textarea"),
        F("description", "Description", "વર્ણન", kind="textarea"),
    ]


class PurchaseIn(BaseModel):
    stockyard_purchase_date: date
    stockyard_id: int
    farmer_id: int
    grain_id: int
    grain_rate_per_20kg: Annotated[int, Field(gt=0, le=1_000_000)]
    pay_after_no_of_days: Annotated[int, Field(ge=0, le=3650)]
    no_of_given_empty_bags: Money | None = None
    terms: str | None = None
    description: str | None = None


def purchase_values(p: StockyardPurchase) -> dict:
    return dict(stockyard_purchase_date=p.stockyard_purchase_date.isoformat(), stockyard_id=str(p.stockyard_id), farmer_id=str(p.farmer_id),
                grain_id=str(p.grain_id), grain_rate_per_20kg=str(p.grain_rate_per_20kg), pay_after_no_of_days=str(p.pay_after_no_of_days),
                no_of_given_empty_bags=str(p.no_of_given_empty_bags), terms=p.terms or "", description=p.description or "")


def purchase_snapshot(p: StockyardPurchase) -> dict:
    return dict(stockyard_purchase_date=p.stockyard_purchase_date, stockyard_id=p.stockyard_id, farmer_id=p.farmer_id, grain_id=p.grain_id,
                grain_rate_per_20kg=p.grain_rate_per_20kg, pay_after_no_of_days=p.pay_after_no_of_days, no_of_given_empty_bags=p.no_of_given_empty_bags,
                terms=p.terms, description=p.description)


async def entry_fields(db: AsyncSession, village_id: int = 0, grain_id: int = 0) -> list[F]:
    stmt = select(StockyardPurchase).order_by(StockyardPurchase.stockyard_purchase_date.desc(), StockyardPurchase.id.desc())
    if village_id:
        stmt = stmt.where(StockyardPurchase.farmer_id.in_(select(Farmer.id).where(Farmer.village_id == village_id)))
    if grain_id:
        stmt = stmt.where(StockyardPurchase.grain_id == grain_id)
    purchases = list((await db.scalars(stmt)).unique().all())
    groups = list((await db.scalars(select(LabourGroup).order_by(LabourGroup.group_name))).all())
    return [
        F("stockyard_purchase_entry_date", "Date", "તારીખ", kind="date", required=True),
        F("stockyard_purchase_id", "Stockyard purchase", "સ્ટોકયાર્ડ ખરીદી", kind="select", required=True,
          options=_opt(purchases, lambda p: f"#{p.id} · {p.stockyard_purchase_date} · {p.farmer.farmer_name} · {p.grain.grain_name} @ ₹ {p.grain_rate_per_20kg}"),
          help=("Grain, rate and pay-after come from this purchase", "અનાજ, ભાવ અને ચુકવણીની મુદત આ ખરીદીમાંથી")),
        F("no_of_filled_bags", "Filled bags", "ભરેલી બેગ", kind="int", required=True),
        F("extra_kilos", "Extra kilos", "વધારાના કિલો", kind="int"),
        F("borrowed_amount", "Borrowed amount to deduct (₹)", "ઉધાર કાપવાના (₹)", kind="int",
          help=("Payable = (bags × bag weight + extra kilos) ÷ 20 × rate; due date = date + pay-after days", "ચૂકવવાપાત્ર = (બેગ × બેગ વજન + વધારાના કિલો) ÷ 20 × ભાવ; મુદત = તારીખ + દિવસ")),
        F("expected_raw_weight_per_bag", "Expected raw weight per bag (kg)", "બેગ દીઠ અપેક્ષિત કાચું વજન (કિલો)", kind="decimal",
          help=("Leave blank to start at the grain's expected raw weight per bag", "ખાલી રાખો તો અનાજના અપેક્ષિત કાચા વજનથી શરૂ થશે")),
        F("grain_quality_code", "Grain quality code", "અનાજ ગુણવત્તા કોડ", kind="textarea"),
        F("no_of_received_empty_bags", "Empty bags received back", "પાછી મળેલી ખાલી બેગ", kind="int",
          help=("Leave blank to start at: bags given − filled bags of the purchase − bags already received back. If that is below zero the purchase's given bags are opened for editing",
                "ખાલી રાખો તો: આપેલી − ખરીદીની ભરેલી − પહેલા પાછી આવેલી. શૂન્યથી ઓછું આવે તો ખરીદીની આપેલી બેગ સુધારવા ખુલશે")),
        F("labour_group_id", "Labour group", "મજૂર જૂથ", kind="select", options=_opt(groups, lambda g: g.group_name)),
        F("description", "Description", "વર્ણન", kind="textarea"),
    ]


class EntryIn(BaseModel):
    stockyard_purchase_entry_date: date
    stockyard_purchase_id: int
    no_of_filled_bags: Annotated[int, Field(ge=0, le=INT_MAX)]
    extra_kilos: Money | None = None
    borrowed_amount: Money | None = None
    expected_raw_weight_per_bag: Annotated[float, Field(ge=0, le=1000)] | None = None
    grain_quality_code: str | None = None
    no_of_received_empty_bags: Money | None = None
    labour_group_id: int | None = None
    description: str | None = None


def entry_values(e: StockyardPurchaseEntry) -> dict:
    return dict(stockyard_purchase_entry_date=e.stockyard_purchase_entry_date.isoformat(), stockyard_purchase_id=str(e.stockyard_purchase_id),
                no_of_filled_bags=str(e.no_of_filled_bags), extra_kilos=str(e.extra_kilos), borrowed_amount=str(e.borrowed_amount),
                expected_raw_weight_per_bag=f"{e.expected_raw_weight_per_bag:g}", grain_quality_code=e.grain_quality_code or "", no_of_received_empty_bags=str(e.no_of_received_empty_bags), labour_group_id=str(e.labour_group_id or ""), description=e.description or "")


def entry_snapshot(e: StockyardPurchaseEntry) -> dict:
    return dict(stockyard_purchase_entry_date=e.stockyard_purchase_entry_date, stockyard_purchase_id=e.stockyard_purchase_id, no_of_filled_bags=e.no_of_filled_bags,
                extra_kilos=e.extra_kilos, payable_amount=e.payable_amount, borrowed_amount=e.borrowed_amount, due_date=e.due_date,
                expected_raw_weight_per_bag=e.expected_raw_weight_per_bag,
                grain_quality_code=e.grain_quality_code, no_of_received_empty_bags=e.no_of_received_empty_bags, labour_group_id=e.labour_group_id, description=e.description)


async def arrangement_fields(db: AsyncSession, keep_entry_id: int | None = None, village_id: int = 0, grain_id: int = 0) -> list[F]:
    """`keep_entry_id`: the entry the record being edited already uses, so it stays in the list. Entries that are already arranged are left out."""
    arranged = select(StockyardArrangementEntry.stockyard_purchase_entry_id).where(StockyardArrangementEntry.stockyard_purchase_entry_id.is_not(None))
    open_entry = StockyardPurchaseEntry.id.not_in(arranged)
    if keep_entry_id:
        open_entry = open_entry | (StockyardPurchaseEntry.id == keep_entry_id)
    stmt = select(StockyardPurchaseEntry).where(open_entry).order_by(StockyardPurchaseEntry.stockyard_purchase_entry_date.desc(), StockyardPurchaseEntry.id.desc())
    entries = list((await db.scalars(stmt)).unique().all())
    entries = [e for e in entries if e.id == keep_entry_id or ((not village_id or e.purchase.farmer.village_id == village_id) and (not grain_id or e.purchase.grain_id == grain_id))]
    groups = list((await db.scalars(select(LabourGroup).order_by(LabourGroup.group_name))).all())
    return [
        F("stockyard_arrangement_date", "Date", "તારીખ", kind="date", required=True),
        F("stockyard_purchase_entry_id", "Stockyard purchase entry (optional)", "સ્ટોકયાર્ડ ખરીદી નોંધ (વૈકલ્પિક)", kind="select",
          options=_opt(entries, lambda e: f"#{e.id} · {e.stockyard_purchase_entry_date} · {e.purchase.farmer.farmer_name} · {e.purchase.grain.grain_name} · {e.no_of_filled_bags} bags"),
          help=("When chosen, the arranged bags are the filled bags of that entry", "પસંદ કરો તો ગોઠવેલી બેગ એ નોંધની ભરેલી બેગ જેટલી")),
        F("labour_group_id", "Labour group", "મજૂર જૂથ", kind="select", options=_opt(groups, lambda g: g.group_name)),
        F("no_of_arranged_bags", "Arranged bags", "ગોઠવેલી બેગ", kind="int",
          help=("Required when no purchase entry is chosen", "ખરીદી નોંધ પસંદ ન કરી હોય ત્યારે જરૂરી")),
        F("rate_per_arranged_bag", "Rate per arranged bag (₹, 1 to 20)", "ગોઠવેલી બેગ દીઠ ભાવ (₹, 1 થી 20)", kind="int", required=True),
        F("description", "Description", "વર્ણન", kind="textarea"),
    ]


class ArrangementIn(BaseModel):
    stockyard_arrangement_date: date
    stockyard_purchase_entry_id: int | None = None
    labour_group_id: int | None = None
    no_of_arranged_bags: Annotated[int, Field(gt=0, le=INT_MAX)] | None = None
    rate_per_arranged_bag: Annotated[int, Field(ge=1, le=20)]
    description: str | None = None


def arrangement_values(a: StockyardArrangementEntry) -> dict:
    return dict(stockyard_arrangement_date=a.stockyard_arrangement_date.isoformat(), stockyard_purchase_entry_id=str(a.stockyard_purchase_entry_id or ""),
                labour_group_id=str(a.labour_group_id or ""), no_of_arranged_bags=str(a.no_of_arranged_bags), rate_per_arranged_bag=str(a.rate_per_arranged_bag),
                description=a.description or "")


def arrangement_snapshot(a: StockyardArrangementEntry) -> dict:
    return dict(stockyard_arrangement_date=a.stockyard_arrangement_date, stockyard_purchase_entry_id=a.stockyard_purchase_entry_id, labour_group_id=a.labour_group_id,
                no_of_arranged_bags=a.no_of_arranged_bags, rate_per_arranged_bag=a.rate_per_arranged_bag, description=a.description)


# ---- farmer to stockyard (filled bags brought from a farmer's place)

def _source_key(t: FarmerStockyardTransfer) -> str:
    return f"g:{t.purchase_farmer_entry_id}" if t.purchase_farmer_entry_id is not None else f"i:{t.purchase_individual_id}"


async def transfer_fields(db: AsyncSession, keep_source: str | None = None, exclude_transfer_id: int | None = None, village_id: int = 0, grain_id: int = 0) -> list[F]:
    """`keep_source`: the farmer entry the transfer being edited already uses, so it stays in the list although it may now have no bags left."""
    yards = list((await db.scalars(select(Stockyard).order_by(Stockyard.name_of_stockyard))).all())
    group = list((await db.scalars(select(PurchaseFarmerEntry).order_by(PurchaseFarmerEntry.purchase_entry_date.desc(), PurchaseFarmerEntry.id.desc()).limit(500))).unique().all())
    direct = list((await db.scalars(select(PurchaseIndividual).order_by(PurchaseIndividual.purchase_individual_date.desc(), PurchaseIndividual.id.desc()).limit(500))).unique().all())
    group = [e for e in group if keep_source == f"g:{e.id}" or ((not village_id or e.purchase_group.village_id == village_id) and (not grain_id or e.purchase_group.grain_id == grain_id))]
    direct = [e for e in direct if keep_source == f"i:{e.id}" or ((not village_id or e.village_id == village_id) and (not grain_id or e.grain_id == grain_id))]
    g_stock = await stock_by_entry(db, [e.id for e in group], exclude_transfer_id=exclude_transfer_id) if group else {}
    d_stock = await stock_by_entry(db, [e.id for e in direct], individual=True, exclude_transfer_id=exclude_transfer_id) if direct else {}
    options = []
    for e in group:
        left = g_stock[e.id].available
        if left > 0 or keep_source == f"g:{e.id}":
            options.append((f"g:{e.id}", f"{e.purchase_group.village.village_name} · {e.farmer.farmer_name} · {e.purchase_group.grain.grain_name} · {e.purchase_entry_date} — {left} bags at farmer (group #{e.purchase_group_id})"))
    for e in direct:
        left = d_stock[e.id].available
        if left > 0 or keep_source == f"i:{e.id}":
            options.append((f"i:{e.id}", f"{e.village.village_name} · {e.farmer.farmer_name} · {e.grain.grain_name} · {e.purchase_individual_date} — {left} bags at farmer (individual)"))
    return [
        F("transfer_date", "Date", "તારીખ", kind="date", required=True),
        F("source", "Farmer entry (village · farmer · grain)", "ખેડૂત નોંધ (ગામ · ખેડૂત · અનાજ)", kind="select", required=True, options=tuple(options),
          help=("From /PurchaseGroup or /PurchaseIndividual; only entries with bags still at the farmer's place are listed", "/PurchaseGroup અથવા /PurchaseIndividual માંથી; ખેડૂત પાસે બેગ બાકી હોય તે જ નોંધ")),
        F("stockyard_id", "To stockyard", "સ્ટોકયાર્ડમાં", kind="select", required=True, options=_opt(yards, lambda y: f"{y.name_of_stockyard} — {y.location}")),
        F("no_of_transferred_bags", "Bags brought", "લાવેલી બેગ", kind="int", required=True,
          help=("All or part of the bags left at the farmer's place", "ખેડૂત પાસે બાકી બેગમાંથી બધી અથવા થોડી")),
        F("description", "Description (e.g. wedding, function)", "વર્ણન (દા.ત. લગ્ન, પ્રસંગ)", kind="textarea"),
    ]


class TransferIn(BaseModel):
    transfer_date: date
    source: str
    stockyard_id: int
    no_of_transferred_bags: Annotated[int, Field(gt=0, le=INT_MAX)]
    description: str | None = None


def transfer_values(t: FarmerStockyardTransfer) -> dict:
    return dict(transfer_date=t.transfer_date.isoformat(), source=_source_key(t), stockyard_id=str(t.stockyard_id), no_of_transferred_bags=str(t.no_of_transferred_bags), description=t.description or "")


def transfer_snapshot(t: FarmerStockyardTransfer) -> dict:
    return dict(transfer_date=t.transfer_date, purchase_farmer_entry_id=t.purchase_farmer_entry_id, purchase_individual_id=t.purchase_individual_id,
                stockyard_id=t.stockyard_id, no_of_transferred_bags=t.no_of_transferred_bags, description=t.description)


# ---- empty bags (bought into a stockyard: seller + mover)

async def empty_bag_fields(db: AsyncSession, village_id: int = 0, grain_id: int = 0) -> list[F]:
    yards = list((await db.scalars(select(Stockyard).order_by(Stockyard.name_of_stockyard))).all())
    grains = list((await db.scalars(select(Grain).order_by(Grain.grain_name))).all())
    sellers = list((await db.scalars(select(EmptyBagSeller).order_by(EmptyBagSeller.pet_name))).all())
    movers = list((await db.scalars(select(EmptyBagMover).order_by(EmptyBagMover.pet_name))).all())
    industries = list((await db.scalars(select(Industry).order_by(Industry.industry_name))).all())
    return [
        F("empty_bags_entry_date", "Date", "તારીખ", kind="date", required=True),
        F("stockyard_id", "Stockyard", "સ્ટોકયાર્ડ", kind="select", required=True, options=_opt(yards, lambda y: f"{y.name_of_stockyard} — {y.location}")),
        F("grain_id", "Grain", "અનાજ", kind="select", required=True, options=_opt(grains, lambda g: g.grain_name)),
        F("empty_bag_seller_id", "Empty bag seller", "ખાલી બારદાન વેચનાર", kind="select", options=_opt(sellers, lambda x: f"{x.pet_name} — {x.name}")),
        F("industry_id", "Industry (when bought from an industry)", "ઉદ્યોગ (ઉદ્યોગ પાસેથી ખરીદી હોય ત્યારે)", kind="select", options=_opt(industries, lambda x: f"{x.industry_name} — {x.location}"),
          help=("Pick either an empty bag seller or an industry: the one picked is paid for these bags", "ખાલી બારદાન વેચનાર અથવા ઉદ્યોગ પસંદ કરો: જેને પસંદ કર્યો તેને આ બેગના પૈસા ચૂકવાય")),
        F("empty_bag_mover_id", "Empty bag mover", "ખાલી બારદાન મૂવર", kind="select", options=_opt(movers, lambda x: f"{x.pet_name} — {x.name}")),
        F("no_of_empty_bags", "Empty bags", "ખાલી બેગ", kind="int", required=True,
          help=("Bags used by stockyard purchase entries are taken off automatically", "સ્ટોકયાર્ડ ખરીદી નોંધમાં વપરાયેલી બેગ આપમેળે ઘટે છે")),
        F("rate_per_empty_bag", "Rate per empty bag (₹)", "ખાલી બેગ દીઠ ભાવ (₹)", kind="int",
          help=("Amount payable = rate × bags; leave 0 when nothing is paid for these bags", "ચૂકવવાપાત્ર = ભાવ × બેગ; પૈસા ન ચૂકવવાના હોય તો 0 રાખો")),
        F("description", "Description", "વર્ણન", kind="textarea"),
    ]


class EmptyBagIn(BaseModel):
    empty_bags_entry_date: date
    stockyard_id: int
    grain_id: int
    empty_bag_seller_id: int | None = None
    empty_bag_mover_id: int | None = None
    industry_id: int | None = None
    no_of_empty_bags: Annotated[int, Field(gt=0, le=INT_MAX)]
    rate_per_empty_bag: Annotated[int, Field(ge=0, le=1_000_000)] | None = None
    description: str | None = None


def empty_bag_values(m: EmptyBag) -> dict:
    return dict(empty_bags_entry_date=m.empty_bags_entry_date.isoformat(), stockyard_id=str(m.stockyard_id), grain_id=str(m.grain_id),
                empty_bag_seller_id=str(m.empty_bag_seller_id or ""), empty_bag_mover_id=str(m.empty_bag_mover_id or ""), industry_id=str(m.industry_id or ""), no_of_empty_bags=str(m.no_of_empty_bags), rate_per_empty_bag=str(m.rate_per_empty_bag), description=m.description or "")


def empty_bag_snapshot(m: EmptyBag) -> dict:
    return dict(empty_bags_entry_date=m.empty_bags_entry_date, stockyard_id=m.stockyard_id, grain_id=m.grain_id, empty_bag_seller_id=m.empty_bag_seller_id,
                empty_bag_mover_id=m.empty_bag_mover_id, industry_id=m.industry_id, no_of_empty_bags=m.no_of_empty_bags, rate_per_empty_bag=m.rate_per_empty_bag,
                description=m.description)


FIELDS = {"purchases": purchase_fields, "entries": entry_fields, "arrangements": arrangement_fields, "transfers": transfer_fields, "empty_bags": empty_bag_fields}
VALUES = {"purchases": purchase_values, "entries": entry_values, "arrangements": arrangement_values, "transfers": transfer_values, "empty_bags": empty_bag_values}
NEW_VALUES = {
    "purchases": lambda: dict(stockyard_purchase_date=today().isoformat(), no_of_given_empty_bags="0"),
    "entries": lambda: dict(stockyard_purchase_entry_date=today().isoformat(), extra_kilos="0", borrowed_amount="0"),
    "arrangements": lambda: dict(stockyard_arrangement_date=today().isoformat()),
    "transfers": lambda: dict(transfer_date=today().isoformat()),
    "empty_bags": lambda: dict(empty_bags_entry_date=today().isoformat(), rate_per_empty_bag="0"),
}


async def _arrangement_extras(db: AsyncSession) -> dict:
    """For the arrangement form: filled bags of every purchase entry, and the rate of the latest arrangement saved (a fallback for the browser's remembered rate)."""
    bags = {str(i): n for i, n in (await db.execute(select(StockyardPurchaseEntry.id, StockyardPurchaseEntry.no_of_filled_bags))).all()}
    last = await db.scalar(select(StockyardArrangementEntry.rate_per_arranged_bag).order_by(StockyardArrangementEntry.id.desc()).limit(1))
    return dict(entry_bags=bags, last_rate=last)


def _page(kind: str) -> str:
    return "stockyard_arrangement_form_page.html" if kind == "arrangements" else "master_form_page.html"


def _ctx(kind: str, fields: list[F], values: dict, errors: dict, obj_id: int | None) -> dict:
    action = f"/StockyardPurchase/{kind}" + (f"/{obj_id}" if obj_id else "")
    return form_context(fields=fields, values=values, errors=errors, action=action, heading=HEADINGS[kind][1 if obj_id else 0], back_url=_back(kind))


@router.get("/{kind}/New", response_class=HTMLResponse)
async def stockyard_new(request: Request, kind: str, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    _tab(kind)
    extra = await _arrangement_extras(db) if kind == "arrangements" else {}
    village_id, grain_id = toolbar_ids(request)  # narrow the pick lists; the grain also starts the grain field
    if kind == "arrangements":
        fields = await arrangement_fields(db, None, village_id, grain_id)
    elif kind == "transfers":
        fields = await transfer_fields(db, None, None, village_id, grain_id)
    else:
        fields = await FIELDS[kind](db, village_id, grain_id)
    ctx = _ctx(kind, fields, apply_toolbar(request, NEW_VALUES[kind]()), {}, None)
    return render_with_csrf(request, csrf, _page(kind), user=user, obj_id=None, **extra, **ctx)


@router.get("/{kind}/{obj_id}/Edit", response_class=HTMLResponse)
async def stockyard_edit(request: Request, kind: str, obj_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    obj = await db.get(TAB_MODELS[_tab(kind)], obj_id)
    if obj is None:
        raise HTTPException(404)
    extra = await _arrangement_extras(db) if kind == "arrangements" else {}
    if kind == "arrangements":
        fields = await arrangement_fields(db, obj.stockyard_purchase_entry_id)
    elif kind == "transfers":
        fields = await transfer_fields(db, _source_key(obj), obj.id)
    else:
        fields = await FIELDS[kind](db)
    errors = {}
    if kind == "purchases" and (need := request.query_params.get("need", "")).isdigit():  # sent here by a purchase entry that needs more empty bags
        errors["no_of_given_empty_bags"] = (f"The entry needs {need} more empty bags than were given: raise the bags given", f"નોંધ માટે {need} ખાલી બેગ વધુ જોઈએ: આપેલી બેગ વધારો")
    ctx = _ctx(kind, fields, VALUES[kind](obj), errors, obj_id)
    return render_with_csrf(request, csrf, _page(kind), user=user, obj_id=obj_id, focus=request.query_params.get("focus", ""), **extra, **ctx)


@router.post("/{kind}", response_class=HTMLResponse)
async def stockyard_create(request: Request, kind: str, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    _tab(kind)
    await csrf.validate_csrf(request)
    return await SAVERS[kind](request, None, user, db)


@router.post("/{kind}/{obj_id}", response_class=HTMLResponse)
async def stockyard_update(request: Request, kind: str, obj_id: int, user: User = Depends(current_user), csrf: CsrfProtect = Depends(), db: AsyncSession = Depends(get_db)):
    _tab(kind)
    await csrf.validate_csrf(request)
    obj = await db.get(TAB_MODELS[kind], obj_id)
    if obj is None:
        raise HTTPException(404)
    return await SAVERS[kind](request, obj, user, db)


# ================================================================== saving

async def _open_year(db: AsyncSession, new_date: date, old_date: date | None) -> str:
    year = await assert_year_open(db, new_date)
    if old_date is not None:
        await assert_year_editable(db, old_date)
    return year


async def _balances(db: AsyncSession, keys: set[tuple[int, int]]) -> dict[tuple[int, int], tuple[int, int]]:
    """(filled balance, empty balance) of each (stockyard, grain)."""
    out = {}
    for sy, gr in keys:
        out[(sy, gr)] = ((await filled_ledger(db, sy, gr)).get((sy, gr), Filled()).balance, (await empty_ledger(db, sy, gr)).get((sy, gr), Empty()).balance)
    return out


async def _bag_problem(db: AsyncSession, keys: set[tuple[int, int]], before: dict[tuple[int, int], tuple[int, int]]) -> tuple[str, str] | None:
    """After a change (flushed, not yet committed): a message when it leaves a stockyard with fewer filled / empty bags than none.
    A balance that was already negative and did not get worse is not blamed on this change."""
    for key, (filled_after, empty_after) in (await _balances(db, keys)).items():
        filled_before, empty_before = before[key]
        if filled_after < 0 and filled_after < filled_before:
            return (f"The stockyard would be short of {-filled_after} filled bags of this grain (they are already loaded on trucks)",
                    f"સ્ટોકયાર્ડમાં આ અનાજની {-filled_after} ભરેલી બેગ ઓછી પડશે (તે ટ્રકમાં ભરાઈ ગઈ છે)")
        if empty_after < 0 and empty_after < empty_before:
            return (f"Not enough empty bags in the stockyard for this grain: short by {-empty_after}. Add the empty bags first (Empty bags tab)",
                    f"સ્ટોકયાર્ડમાં આ અનાજની ખાલી બેગ પૂરતી નથી: {-empty_after} ઓછી. પહેલા મળેલી ખાલી બેગ ઉમેરો (ખાલી બેગ ટેબ)")
    return None


async def _commit(db: AsyncSession, kind: str, rerender, field: str):
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return rerender({field: GENERIC_ERROR})
    return Response(status_code=204, headers={"HX-Redirect": _back(kind)})


async def _save_purchase(request: Request, p: StockyardPurchase | None, user: User, db: AsyncSession):
    p_id = p.id if p else None
    fields = await purchase_fields(db)
    raw = await read_form(request)
    rerender = lambda errs: render(request, "partials/master_form.html", **_ctx("purchases", fields, raw, errs, p_id))  # noqa: E731
    clean, errors = run_validation(PurchaseIn, fields, normalize_fields(fields, raw))
    if errors:
        return rerender(errors)
    clean["no_of_given_empty_bags"] = clean["no_of_given_empty_bags"] or 0
    for name, model in (("stockyard_id", Stockyard), ("farmer_id", Farmer), ("grain_id", Grain)):
        if await db.get(model, clean[name]) is None:
            return rerender({name: ("Unknown value", "અજ્ઞાત કિંમત")})
    try:
        clean["business_year"] = await _open_year(db, clean["stockyard_purchase_date"], p.stockyard_purchase_date if p else None)
    except YearLockedError as exc:
        return rerender({"stockyard_purchase_date": YEAR_LOCKED(exc)})
    keys = {(clean["stockyard_id"], clean["grain_id"])} | ({(p.stockyard_id, p.grain_id)} if p else set())
    balances = await _balances(db, keys)
    before = None
    if p is not None:
        before = purchase_snapshot(p)
        grain = await db.get(Grain, clean["grain_id"])
        entries = list((await db.scalars(select(StockyardPurchaseEntry).where(StockyardPurchaseEntry.stockyard_purchase_id == p.id))).unique().all())
        for e in entries:  # rate, grain and pay-after drive every entry's payable amount and due date
            new_payable = payable_amount(e.no_of_filled_bags, e.extra_kilos, grain.net_bag_weight, clean["grain_rate_per_20kg"])
            if e.borrowed_amount > new_payable:
                return rerender({"grain_rate_per_20kg": (f"Entry #{e.id} has borrowed ₹ {e.borrowed_amount}, more than its new payable amount (₹ {new_payable})",
                                                         f"નોંધ #{e.id} માં ઉધાર ₹ {e.borrowed_amount} છે, જે નવી ચૂકવવાપાત્ર રકમ (₹ {new_payable}) થી વધુ છે")})
        for name, value in clean.items():
            setattr(p, name, value)
        for e in entries:
            old = entry_snapshot(e)
            e.payable_amount = payable_amount(e.no_of_filled_bags, e.extra_kilos, grain.net_bag_weight, clean["grain_rate_per_20kg"])
            e.due_date = e.stockyard_purchase_entry_date + timedelta(days=clean["pay_after_no_of_days"])
            if changed := audit.diff(old, entry_snapshot(e)):
                audit.log(db, user, "update", "stockyard_purchase_entries", e.id, changed)
    else:
        p = StockyardPurchase(created_by=user.id, **clean)
        db.add(p)
    await db.flush()
    if problem := await _bag_problem(db, keys, balances):
        await db.rollback()
        return rerender({"no_of_given_empty_bags": problem})
    audit.log(db, user, "update" if before else "create", "stockyard_purchases", p.id, audit.diff(before, purchase_snapshot(p)))
    return await _commit(db, "purchases", rerender, "grain_rate_per_20kg")


async def _save_entry(request: Request, e: StockyardPurchaseEntry | None, user: User, db: AsyncSession):
    e_id = e.id if e else None
    fields = await entry_fields(db)
    raw = await read_form(request)
    rerender = lambda errs: render(request, "partials/master_form.html", **_ctx("entries", fields, raw, errs, e_id))  # noqa: E731
    clean, errors = run_validation(EntryIn, fields, normalize_fields(fields, raw))
    if errors:
        return rerender(errors)
    clean["extra_kilos"] = clean["extra_kilos"] or 0
    clean["borrowed_amount"] = clean["borrowed_amount"] or 0
    purchase = await db.get(StockyardPurchase, clean["stockyard_purchase_id"])
    if purchase is None:
        return rerender({"stockyard_purchase_id": ("Unknown value", "અજ્ઞાત કિંમત")})
    if clean["labour_group_id"] is not None and await db.get(LabourGroup, clean["labour_group_id"]) is None:
        return rerender({"labour_group_id": ("Unknown labour group", "અજ્ઞાત મજૂર જૂથ")})
    try:
        clean["business_year"] = await _open_year(db, clean["stockyard_purchase_entry_date"], e.stockyard_purchase_entry_date if e else None)
    except YearLockedError as exc:
        return rerender({"stockyard_purchase_entry_date": YEAR_LOCKED(exc)})
    if clean["expected_raw_weight_per_bag"] is None:  # starts at the grain's value, editable
        clean["expected_raw_weight_per_bag"] = purchase.grain.expected_raw_weight_per_bag
    clean["payable_amount"] = payable_amount(clean["no_of_filled_bags"], clean["extra_kilos"], purchase.grain.net_bag_weight, purchase.grain_rate_per_20kg)
    clean["due_date"] = clean["stockyard_purchase_entry_date"] + timedelta(days=purchase.pay_after_no_of_days)
    if clean["borrowed_amount"] > clean["payable_amount"]:
        return rerender({"borrowed_amount": (f"Cannot exceed the amount payable (₹ {clean['payable_amount']})", f"ચૂકવવાપાત્ર રકમ (₹ {clean['payable_amount']}) થી વધુ ન હોઈ શકે")})
    if (dup := await find_duplicate(db, purchase.farmer_id, clean["stockyard_purchase_entry_date"], purchase.grain_id, purchase.grain_rate_per_20kg,
                                    clean["no_of_filled_bags"], clean["extra_kilos"], ("stockyard_purchase_entries", e.id) if e else None)):
        return rerender({"no_of_filled_bags": DUPLICATE_MSG(dup)})
    keys = {(purchase.stockyard_id, purchase.grain_id)} | ({(e.purchase.stockyard_id, e.purchase.grain_id)} if e else set())
    for sy, gr in keys:
        await advisory_lock(db, "stockyard_bags", sy * 1000 + gr)  # two clerks must not both take the last empty bags
    if clean["no_of_received_empty_bags"] is None:  # starts at given - filled - already received; editable
        others = select(func.coalesce(func.sum(StockyardPurchaseEntry.no_of_filled_bags), 0), func.coalesce(func.sum(StockyardPurchaseEntry.no_of_received_empty_bags), 0)).where(
            StockyardPurchaseEntry.stockyard_purchase_id == purchase.id)
        if e is not None:
            others = others.where(StockyardPurchaseEntry.id != e.id)
        other_filled, other_received = (await db.execute(others)).one()
        clean["no_of_received_empty_bags"] = default_received(purchase.no_of_given_empty_bags, int(other_filled) + clean["no_of_filled_bags"], int(other_received))
        if clean["no_of_received_empty_bags"] < 0:  # the farmer needed more empty bags than were given: raise them on the purchase
            need = -clean["no_of_received_empty_bags"]
            return Response(status_code=204, headers={"HX-Redirect": f"/StockyardPurchase/purchases/{purchase.id}/Edit?focus=no_of_given_empty_bags&need={need}"})
    balances = await _balances(db, keys)
    before = None
    if e is not None:
        before = entry_snapshot(e)
        for name, value in clean.items():
            setattr(e, name, value)
        for a in (await db.scalars(select(StockyardArrangementEntry).where(StockyardArrangementEntry.stockyard_purchase_entry_id == e.id))).unique().all():
            if a.no_of_arranged_bags != e.no_of_filled_bags:  # an arrangement of an entry always covers all its filled bags
                if e.no_of_filled_bags <= 0:
                    return rerender({"no_of_filled_bags": ("An arrangement entry uses this entry's bags; they must stay above zero", "ગોઠવણી નોંધ આ નોંધની બેગ વાપરે છે; તે શૂન્યથી વધુ રહેવી જોઈએ")})
                old = arrangement_snapshot(a)
                a.no_of_arranged_bags = e.no_of_filled_bags
                audit.log(db, user, "update", "stockyard_arrangement_entries", a.id, audit.diff(old, arrangement_snapshot(a)))
    else:
        e = StockyardPurchaseEntry(created_by=user.id, **clean)
        db.add(e)
    await db.flush()
    if problem := await _bag_problem(db, keys, balances):
        await db.rollback()
        return rerender({"no_of_filled_bags": problem})
    audit.log(db, user, "update" if before else "create", "stockyard_purchase_entries", e.id, audit.diff(before, entry_snapshot(e)))
    return await _commit(db, "entries", rerender, "no_of_filled_bags")


async def _save_arrangement(request: Request, a: StockyardArrangementEntry | None, user: User, db: AsyncSession):
    a_id = a.id if a else None
    fields = await arrangement_fields(db, a.stockyard_purchase_entry_id if a else None)
    raw = await read_form(request)
    rerender = lambda errs: render(request, "partials/master_form.html", **_ctx("arrangements", fields, raw, errs, a_id))  # noqa: E731
    clean, errors = run_validation(ArrangementIn, fields, normalize_fields(fields, raw))
    if errors:
        return rerender(errors)
    if clean["labour_group_id"] is not None and await db.get(LabourGroup, clean["labour_group_id"]) is None:
        return rerender({"labour_group_id": ("Unknown labour group", "અજ્ઞાત મજૂર જૂથ")})
    if clean["stockyard_purchase_entry_id"] is not None:
        entry = await db.get(StockyardPurchaseEntry, clean["stockyard_purchase_entry_id"])
        if entry is None:
            return rerender({"stockyard_purchase_entry_id": ("Unknown value", "અજ્ઞાત કિંમત")})
        if entry.no_of_filled_bags <= 0:
            return rerender({"stockyard_purchase_entry_id": ("This entry has no filled bags to arrange", "આ નોંધમાં ગોઠવવા માટે ભરેલી બેગ નથી")})
        clean["no_of_arranged_bags"] = entry.no_of_filled_bags
        duplicate = await db.scalar(select(StockyardArrangementEntry.id).where(
            StockyardArrangementEntry.stockyard_purchase_entry_id == entry.id, StockyardArrangementEntry.id != (a.id if a else 0)))
        if duplicate:
            return rerender({"stockyard_purchase_entry_id": (f"Already arranged (arrangement entry #{duplicate}); edit that one instead",
                                                             f"પહેલેથી ગોઠવાયેલ (ગોઠવણી નોંધ #{duplicate}); તે જ સુધારો")})
    elif clean["no_of_arranged_bags"] is None:
        return rerender({"no_of_arranged_bags": ("Required when no purchase entry is chosen", "ખરીદી નોંધ પસંદ ન હોય ત્યારે જરૂરી")})
    try:
        clean["business_year"] = await _open_year(db, clean["stockyard_arrangement_date"], a.stockyard_arrangement_date if a else None)
    except YearLockedError as exc:
        return rerender({"stockyard_arrangement_date": YEAR_LOCKED(exc)})
    before = None
    if a is not None:
        before = arrangement_snapshot(a)
        for name, value in clean.items():
            setattr(a, name, value)
    else:
        a = StockyardArrangementEntry(created_by=user.id, **clean)
        db.add(a)
    await db.flush()
    audit.log(db, user, "update" if before else "create", "stockyard_arrangement_entries", a.id, audit.diff(before, arrangement_snapshot(a)))
    return await _commit(db, "arrangements", rerender, "stockyard_purchase_entry_id")


async def _save_transfer(request: Request, t: FarmerStockyardTransfer | None, user: User, db: AsyncSession):
    t_id = t.id if t else None
    old_source = _source_key(t) if t else None
    fields = await transfer_fields(db, old_source, t_id)
    raw = await read_form(request)
    rerender = lambda errs: render(request, "partials/master_form.html", **_ctx("transfers", fields, raw, errs, t_id))  # noqa: E731
    clean, errors = run_validation(TransferIn, fields, normalize_fields(fields, raw))
    if errors:
        return rerender(errors)
    kind_, _, raw_id = clean["source"].partition(":")
    individual = kind_ == "i"
    entry = await db.get(PurchaseIndividual if individual else PurchaseFarmerEntry, int(raw_id)) if kind_ in ("g", "i") and raw_id.isdigit() else None
    if entry is None:
        return rerender({"source": ("Unknown value", "અજ્ઞાત કિંમત")})
    if await db.get(Stockyard, clean["stockyard_id"]) is None:
        return rerender({"stockyard_id": ("Unknown value", "અજ્ઞાત કિંમત")})
    try:
        clean["business_year"] = await _open_year(db, clean["transfer_date"], t.transfer_date if t else None)
    except YearLockedError as exc:
        return rerender({"transfer_date": YEAR_LOCKED(exc)})
    await advisory_lock(db, "stock_ind" if individual else "stock", entry.id)  # two clerks must not move the same bags twice
    stock = (await stock_by_entry(db, [entry.id], individual=individual, exclude_transfer_id=t_id)).get(entry.id)
    left = stock.available if stock else 0
    if clean["no_of_transferred_bags"] > left:
        return rerender({"no_of_transferred_bags": (f"Only {left} bags are left at this farmer's place", f"આ ખેડૂત પાસે ફક્ત {left} બેગ બાકી છે")})
    grain_id, entry_id = entry.grain.id, entry.id
    del clean["source"]
    clean["purchase_farmer_entry_id"], clean["purchase_individual_id"] = (None, entry_id) if individual else (entry_id, None)
    keys = {(clean["stockyard_id"], grain_id)} | ({(t.stockyard_id, t.grain.id)} if t else set())
    balances = await _balances(db, keys)
    before = None
    if t is not None:
        before = transfer_snapshot(t)
        for name, value in clean.items():
            setattr(t, name, value)
    else:
        t = FarmerStockyardTransfer(created_by=user.id, **clean)
        db.add(t)
    await db.flush()
    if problem := await _bag_problem(db, keys, balances):
        await db.rollback()
        return rerender({"no_of_transferred_bags": problem})
    audit.log(db, user, "update" if before else "create", "farmer_to_stockyard_transfers", t.id, audit.diff(before, transfer_snapshot(t)))
    return await _commit(db, "transfers", rerender, "no_of_transferred_bags")


async def _save_empty_bag(request: Request, m: EmptyBag | None, user: User, db: AsyncSession):
    m_id = m.id if m else None
    fields = await empty_bag_fields(db)
    raw = await read_form(request)
    rerender = lambda errs: render(request, "partials/master_form.html", **_ctx("empty_bags", fields, raw, errs, m_id))  # noqa: E731
    clean, errors = run_validation(EmptyBagIn, fields, normalize_fields(fields, raw))
    if errors:
        return rerender(errors)
    for name, model in (("stockyard_id", Stockyard), ("grain_id", Grain), ("empty_bag_seller_id", EmptyBagSeller), ("empty_bag_mover_id", EmptyBagMover), ("industry_id", Industry)):
        if clean[name] is not None and await db.get(model, clean[name]) is None:
            return rerender({name: ("Unknown value", "અજ્ઞાત કિંમત")})
    if clean["empty_bag_seller_id"] is not None and clean["industry_id"] is not None:
        return rerender({"industry_id": ("Pick either a seller or an industry, not both", "વેચનાર અથવા ઉદ્યોગ પસંદ કરો, બંને નહીં")})
    clean["rate_per_empty_bag"] = clean["rate_per_empty_bag"] or 0
    if clean["rate_per_empty_bag"] and clean["empty_bag_seller_id"] is None and clean["industry_id"] is None:
        return rerender({"rate_per_empty_bag": ("Pick the seller or industry who is paid for these bags, or set the rate to 0", "જેને ચુકવણી કરવાની છે તે વેચનાર કે ઉદ્યોગ પસંદ કરો, અથવા ભાવ 0 રાખો")})
    new_payable = clean["rate_per_empty_bag"] * clean["no_of_empty_bags"]
    if m is not None:
        paid = await paid_for(db, "empty_bag", m.id)
        if paid and (new_payable < paid or (clean["empty_bag_seller_id"], clean["industry_id"]) != (m.empty_bag_seller_id, m.industry_id)):
            return rerender({"rate_per_empty_bag": (f"₹ {paid} is already paid for these bags: the amount cannot go below that and the seller / industry cannot change",
                                              f"આ બેગ માટે ₹ {paid} ચૂકવાઈ ગયા છે: રકમ તેથી ઓછી ન થાય અને વેચનાર / ઉદ્યોગ બદલી ન શકાય")})
    try:
        clean["business_year"] = await _open_year(db, clean["empty_bags_entry_date"], m.empty_bags_entry_date if m else None)
    except YearLockedError as exc:
        return rerender({"empty_bags_entry_date": YEAR_LOCKED(exc)})
    keys = {(clean["stockyard_id"], clean["grain_id"])} | ({(m.stockyard_id, m.grain_id)} if m else set())
    for sy, gr in keys:
        await advisory_lock(db, "stockyard_bags", sy * 1000 + gr)
    balances = await _balances(db, keys)
    before = None
    if m is not None:
        before = empty_bag_snapshot(m)
        for name, value in clean.items():
            setattr(m, name, value)
    else:
        m = EmptyBag(created_by=user.id, **clean)
        db.add(m)
    await db.flush()
    if problem := await _bag_problem(db, keys, balances):
        await db.rollback()
        return rerender({"no_of_empty_bags": problem})
    audit.log(db, user, "update" if before else "create", "empty_bags", m.id, audit.diff(before, empty_bag_snapshot(m)))
    return await _commit(db, "empty_bags", rerender, "no_of_empty_bags")


SAVERS = {"purchases": _save_purchase, "entries": _save_entry, "arrangements": _save_arrangement, "transfers": _save_transfer, "empty_bags": _save_empty_bag}
