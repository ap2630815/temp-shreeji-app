"""Ledger analysis: one report per ledger (farmers, trucks, labour, bag suppliers, brokers, industries).

Each report is plain data (stat cards, tables, bar series) that one template renders. Everything is derived from the
ledger rows for one business year, optionally narrowed by the toolbar's grain / village filters.

Cell kinds: inr (rupees), int, kg, pct, text, date."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BagSupply, LabourGroupWage, LabourWork, Payment, Receipt, TruckTrip
from app.services import receivables as rec_svc
from app.services.ledger import all_entry_views
from app.services.payables import paid_map

Pair = tuple[str, str]  # (English, Gujarati)

LEDGERS: dict[str, Pair] = {
    "farmer": ("Farmers", "ખેડૂતો"),
    "truck": ("Trucks", "ટ્રક"),
    "labour_group": ("Labour", "મજૂર"),
    "bag_supplier": ("Bag suppliers", "બારદાન સપ્લાયર"),
    "broker": ("Brokers", "દલાલ"),
    "industry": ("Industries", "ઉદ્યોગો"),
}

MONTHS = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep"]


@dataclass
class Stat:
    en: str
    gu: str
    value: object
    kind: str = "inr"
    sub: str = ""


@dataclass
class Table:
    title: Pair
    headers: list[tuple[str, str, str]]  # (en, gu, kind)
    rows: list[list]
    total: list | None = None


@dataclass
class Bars:
    title: Pair
    items: list[tuple[str, int]]
    kind: str = "inr"


@dataclass
class Report:
    ledger: str
    stats: list[Stat] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    bars: list[Bars] = field(default_factory=list)
    notes: list[Pair] = field(default_factory=list)


# ---------------------------------------------------------------- pure helpers

def pct(part: int, whole: int) -> Decimal | None:
    """part / whole as a percentage with 2 decimals (half-up); None when whole is zero."""
    if not whole:
        return None
    return (Decimal(part) * 100 / Decimal(whole)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def month_key(d: date) -> str:
    return MONTHS[(d.month - 10) % 12]


def monthly(pairs: list[tuple[date, int]]) -> list[tuple[str, int]]:
    """Sum (date, amount) pairs by month, in business-year order (Oct..Sep), skipping empty months."""
    totals: dict[str, int] = defaultdict(int)
    for d, amount in pairs:
        totals[month_key(d)] += amount
    return [(m, totals[m]) for m in MONTHS if totals.get(m)]


def ageing(dues: list[tuple[date, int]], today: date) -> list[tuple[str, int]]:
    """Outstanding amounts by how long past their due date: (due_date, amount_due) pairs."""
    buckets = {"Not yet due": 0, "1-7 days late": 0, "8-30 days late": 0, "31-90 days late": 0, "Over 90 days late": 0}
    for due_date, amount in dues:
        if amount <= 0:
            continue
        late = (today - due_date).days
        key = ("Not yet due" if late <= 0 else "1-7 days late" if late <= 7 else "8-30 days late" if late <= 30
               else "31-90 days late" if late <= 90 else "Over 90 days late")
        buckets[key] += amount
    return list(buckets.items())


def _sorted_rows(groups: dict, make_row, key=lambda r: r[0]) -> list[list]:
    return sorted((make_row(k, v) for k, v in groups.items()), key=key)


def _sum_cols(rows: list[list], cols: range | list[int]) -> list:
    return [sum(r[i] for r in rows) if i in cols else ("Total" if i == 0 else "") for i in range(len(rows[0]))] if rows else None


class _G(dict):
    """dict of counters that creates missing keys: g[key]['bags'] += 1."""

    def __missing__(self, key):
        self[key] = defaultdict(int)
        return self[key]


def _trip_villages(trip: TruckTrip) -> set[int]:
    return {line.entry.purchase_group.village_id for line in trip.load_lines}


def _keep_trip(trip: TruckTrip, grain_id: int, village_id: int) -> bool:
    return (not grain_id or trip.grain.id == grain_id) and (not village_id or village_id in _trip_villages(trip))


# ---------------------------------------------------------------- payments / receipts blocks

async def _money_blocks(db: AsyncSession, report: Report, *, party_type: str | None, year: str, party_ids: set[int] | None) -> None:
    """How the money actually moved: by method, by status (payments only) and by month."""
    if party_type is None:
        stmt = select(Receipt).where(Receipt.business_year == year)
        rows = [(r.receipt_date, r.amount, r.method, None, r.industry_id) for r in (await db.scalars(stmt)).unique().all()]
        word = (("Receipts", "પ્રાપ્તિ"), ("Received", "મળ્યા"))
    else:
        stmt = select(Payment).where(Payment.business_year == year, Payment.party_type == party_type)
        rows = [(p.payment_date, p.amount, p.method, p.status, p.party_id) for p in (await db.scalars(stmt)).all()]
        word = (("Payments", "ચુકવણીઓ"), ("Paid", "ચૂકવ્યું"))
    if party_ids is not None:
        rows = [r for r in rows if r[4] in party_ids]
    if not rows:
        return
    by_method = _G()
    for _, amount, method, _, _ in rows:
        by_method[method]["n"] += 1
        by_method[method]["amount"] += amount
    method_rows = sorted(([m.upper(), v["n"], v["amount"]] for m, v in by_method.items()), key=lambda r: -r[2])
    report.tables.append(Table(word[0], [("Method", "રીત", "text"), ("Count", "સંખ્યા", "int"), (word[1][0], word[1][1], "inr")], method_rows,
                               ["Total", sum(r[1] for r in method_rows), sum(r[2] for r in method_rows)]))
    if party_type is not None:
        by_status = _G()
        for _, amount, _, status, _ in rows:
            by_status[status]["n"] += 1
            by_status[status]["amount"] += amount
        order = {"complete": 0, "final": 1, "partial": 2}
        report.tables.append(Table(("Payments by status", "સ્થિતિ મુજબ ચુકવણીઓ"), [("Status", "સ્થિતિ", "text"), ("Count", "સંખ્યા", "int"), ("Amount", "રકમ", "inr")],
                                   sorted(([s, v["n"], v["amount"]] for s, v in by_status.items()), key=lambda r: order.get(r[0], 9))))
    report.bars.append(Bars((f"{word[0][0]} by month", f"મહિના મુજબ {word[0][1]}"), monthly([(d, a) for d, a, *_ in rows])))


# ---------------------------------------------------------------- farmers

async def farmer_report(db: AsyncSession, year: str, grain_id: int, village_id: int, today: date) -> Report:
    views = [v for v in await all_entry_views(db) if v.entry.business_year == year
             and (not grain_id or v.entry.grain.id == grain_id) and (not village_id or v.entry.farmer.village_id == village_id)]
    r = Report("farmer")
    net = sum(v.net_payable for v in views)
    r.stats = [
        Stat("Farmers", "ખેડૂતો", len({v.entry.farmer_id for v in views}), "int", f"{len(views)} entries"),
        Stat("Filled bags", "ભરેલી બેગ", sum(v.entry.no_of_filled_bags for v in views), "int", f"+ {sum(v.entry.no_of_handful_bags for v in views)} handful"),
        Stat("Grain bought", "ખરીદેલું અનાજ", sum(v.entry.total_kg for v in views), "kg"),
        Stat("Gross payable", "કુલ ચૂકવવાપાત્ર", sum(v.entry.payable_amount for v in views)),
        Stat("Borrowed (deducted)", "ઉધાર (કપાત)", sum(v.entry.borrowed_amount for v in views)),
        Stat("Net payable", "ચોખ્ખું ચૂકવવાપાત્ર", net),
        Stat("Paid", "ચૂકવ્યું", sum(v.paid for v in views), "inr", f"{pct(sum(v.paid for v in views), net) or 0}% of net"),
        Stat("Due", "બાકી", sum(max(v.due, 0) for v in views)),
        Stat("Overdue", "મુદત વીતી", sum(max(v.due, 0) for v in views if v.is_overdue(today))),
    ]
    by_village = _G()
    farmers_in: dict[str, set] = defaultdict(set)
    for v in views:
        name = v.entry.farmer.village.village_name
        g = by_village[name]
        farmers_in[name].add(v.entry.farmer_id)
        g["bags"] += v.entry.no_of_filled_bags
        g["net"] += v.net_payable
        g["paid"] += v.paid
        g["due"] += max(v.due, 0)
        g["overdue"] += max(v.due, 0) if v.is_overdue(today) else 0
    rows = _sorted_rows(by_village, lambda k, g: [k, len(farmers_in[k]), g["bags"], g["net"], g["paid"], g["due"], g["overdue"]], key=lambda x: -x[3])
    r.tables.append(Table(("By village", "ગામ મુજબ"), [("Village", "ગામ", "text"), ("Farmers", "ખેડૂત", "int"), ("Bags", "બેગ", "int"), ("Net payable", "ચોખ્ખું", "inr"),
                                                    ("Paid", "ચૂકવ્યું", "inr"), ("Due", "બાકી", "inr"), ("Overdue", "મુદત વીતી", "inr")], rows, _sum_cols(rows, [1, 2, 3, 4, 5, 6])))
    by_grain = _G()
    for v in views:
        g = by_grain[v.entry.grain.grain_name]
        g["bags"] += v.entry.no_of_filled_bags
        g["kg"] += v.entry.total_kg
        g["gross"] += v.entry.payable_amount
        g["net"] += v.net_payable
        g["paid"] += v.paid
        g["due"] += max(v.due, 0)
    rows = _sorted_rows(by_grain, lambda k, g: [k, g["bags"], g["kg"], round(g["gross"] * 20 / g["kg"]) if g["kg"] else 0, g["net"], g["paid"], g["due"]], key=lambda x: -x[4])
    r.tables.append(Table(("By grain", "અનાજ મુજબ"), [("Grain", "અનાજ", "text"), ("Bags", "બેગ", "int"), ("Kg", "કિલો", "kg"), ("Avg rate / 20 kg", "સરેરાશ ભાવ / 20 કિ", "inr"),
                                                   ("Net payable", "ચોખ્ખું", "inr"), ("Paid", "ચૂકવ્યું", "inr"), ("Due", "બાકી", "inr")], rows, _sum_cols(rows, [1, 2, 4, 5, 6])))
    by_farmer = _G()
    for v in views:
        g = by_farmer[(v.entry.farmer.farmer_name, v.entry.farmer.village.village_name)]
        g["bags"] += v.entry.no_of_filled_bags
        g["net"] += v.net_payable
        g["paid"] += v.paid
        g["due"] += max(v.due, 0)
    rows = sorted(([k[0], k[1], g["bags"], g["net"], g["paid"], g["due"]] for k, g in by_farmer.items()), key=lambda x: -x[3])[:10]
    r.tables.append(Table(("Top 10 farmers by net payable", "ચોખ્ખા મુજબ ટોચના 10 ખેડૂત"), [("Farmer", "ખેડૂત", "text"), ("Village", "ગામ", "text"), ("Bags", "બેગ", "int"),
                                                                                         ("Net payable", "ચોખ્ખું", "inr"), ("Paid", "ચૂકવ્યું", "inr"), ("Due", "બાકી", "inr")], rows))
    r.bars.append(Bars(("Dues by age", "ઉંમર મુજબ બાકી"), ageing([(v.entry.due_date, v.due) for v in views], today)))
    await _money_blocks(db, r, party_type="farmer", year=year, party_ids={v.entry.farmer_id for v in views} if (grain_id or village_id) else None)
    return r


# ---------------------------------------------------------------- trucks

async def truck_report(db: AsyncSession, year: str, grain_id: int, village_id: int, today: date) -> Report:
    trips = [t for t in (await db.scalars(select(TruckTrip).where(TruckTrip.business_year == year))).unique().all() if _keep_trip(t, grain_id, village_id)]
    paid = await paid_map(db, "truck", [t.id for t in trips])
    r = Report("truck")
    payable = sum(t.total_amount for t in trips)
    paid_total = sum(paid.get(t.id, 0) for t in trips)
    bags = sum(t.bags for t in trips)
    r.stats = [
        Stat("Trips", "ટ્રીપ", len(trips), "int", f"{len({t.truck_id for t in trips})} trucks"),
        Stat("Bags carried", "વહન કરેલી બેગ", bags, "int"),
        Stat("Grain weight", "અનાજનું વજન", sum(t.freight_weight_kg or 0 for t in trips), "kg"),
        Stat("Trip total (freight)", "ટ્રીપ કુલ (ભાડું)", sum(t.trip_total for t in trips)),
        Stat("Advance to drivers", "ડ્રાઇવરને એડવાન્સ", sum(t.advance_amount for t in trips)),
        Stat("Other payable / deduction", "અન્ય ચૂકવવાપાત્ર / કપાત", sum(t.other_payable for t in trips), "inr", f"− {sum(t.other_deduction for t in trips)} deduction"),
        Stat("Payable to owners", "માલિકોને ચૂકવવાપાત્ર", payable, "inr", f"avg {round(payable / len(trips)) if trips else 0} / trip"),
        Stat("Paid", "ચૂકવ્યું", paid_total, "inr", f"{pct(paid_total, payable) or 0}% of payable"),
        Stat("Due", "બાકી", payable - paid_total),
    ]
    head = [("Trips", "ટ્રીપ", "int"), ("Bags", "બેગ", "int"), ("Kg", "કિલો", "kg"), ("Payable", "ચૂકવવાપાત્ર", "inr"), ("Paid", "ચૂકવ્યું", "inr"), ("Due", "બાકી", "inr")]

    def grouped(key_fn, label_head, title, limit=None):
        g = _G()
        for t in trips:
            k = key_fn(t)
            g[k]["trips"] += 1
            g[k]["bags"] += t.bags
            g[k]["kg"] += t.freight_weight_kg or 0
            g[k]["payable"] += t.total_amount
            g[k]["paid"] += paid.get(t.id, 0)
        rows = sorted(([k, v["trips"], v["bags"], v["kg"], v["payable"], v["paid"], v["payable"] - v["paid"]] for k, v in g.items()), key=lambda x: -x[4])
        if limit:
            rows = rows[:limit]
        r.tables.append(Table(title, [label_head, *head], rows, None if limit else _sum_cols(rows, [1, 2, 3, 4, 5, 6])))

    grouped(lambda t: f"{t.truck.truck_number} — {t.truck.truck_owner_name}", ("Truck / owner", "ટ્રક / માલિક", "text"), ("By truck", "ટ્રક મુજબ"))
    grouped(lambda t: t.transporter.pet_name, ("Transport", "ટ્રાન્સપોર્ટ", "text"), ("By transport", "ટ્રાન્સપોર્ટ મુજબ"))
    grouped(lambda t: t.industry.industrialist_name, ("Delivered to", "ક્યાં પહોંચાડ્યું", "text"), ("By industry", "ઉદ્યોગ મુજબ"))
    grouped(lambda t: t.grain.grain_name, ("Grain", "અનાજ", "text"), ("By grain", "અનાજ મુજબ"))
    basis = _G()
    for t in trips:
        k = "Per ton" if t.rent_per_ton else "Per bag"
        basis[k]["trips"] += 1
        basis[k]["freight"] += t.trip_total
    r.tables.append(Table(("Rent basis", "ભાડાની રીત"), [("Basis", "રીત", "text"), ("Trips", "ટ્રીપ", "int"), ("Freight", "ભાડું", "inr")],
                          [[k, v["trips"], v["freight"]] for k, v in basis.items()]))
    r.bars.append(Bars(("Freight payable by month", "મહિના મુજબ ભાડું"), monthly([(t.trip_date, t.total_amount) for t in trips])))
    await _money_blocks(db, r, party_type="truck", year=year, party_ids={t.truck_id for t in trips} if (grain_id or village_id) else None)
    return r


# ---------------------------------------------------------------- labour

async def labour_report(db: AsyncSession, year: str, grain_id: int, village_id: int, today: date) -> Report:
    works = list((await db.scalars(select(LabourWork).where(LabourWork.business_year == year))).unique().all())
    paid = await paid_map(db, "labour_group", [w.id for w in works])
    r = Report("labour_group")
    net = sum(w.net_payable for w in works)
    paid_total = sum(paid.get(w.id, 0) for w in works)
    r.stats = [
        Stat("Work entries", "કામની નોંધ", len(works), "int", f"{len({w.labour_group_id for w in works})} groups"),
        Stat("Wages earned", "મજૂરી", sum(w.payable_amount for w in works)),
        Stat("Borrowing deducted", "ઉધાર કપાત", sum(w.borrowing_amount for w in works)),
        Stat("Net payable", "ચોખ્ખું ચૂકવવાપાત્ર", net),
        Stat("Petrol + meals (business cost)", "પેટ્રોલ + જમવાનું (ખર્ચ)", sum(w.petrol + w.meal for w in works), "inr",
             f"petrol {sum(w.petrol for w in works)} · meal {sum(w.meal for w in works)}"),
        Stat("Paid", "ચૂકવ્યું", paid_total, "inr", f"{pct(paid_total, net) or 0}% of net"),
        Stat("Due", "બાકી", net - paid_total),
    ]
    g = _G()
    for w in works:
        x = g[w.labour_group.group_name]
        x["n"] += 1
        x["wages"] += w.payable_amount
        x["borrow"] += w.borrowing_amount
        x["net"] += w.net_payable
        x["extras"] += w.petrol + w.meal
        x["paid"] += paid.get(w.id, 0)
    rows = sorted(([k, v["n"], v["wages"], v["borrow"], v["net"], v["extras"], v["paid"], v["net"] - v["paid"]] for k, v in g.items()), key=lambda x: -x[4])
    r.tables.append(Table(("By labour group", "મજૂર જૂથ મુજબ"), [("Group", "જૂથ", "text"), ("Entries", "નોંધ", "int"), ("Wages", "મજૂરી", "inr"), ("Borrowing", "ઉધાર", "inr"),
                                                              ("Net", "ચોખ્ખું", "inr"), ("Petrol + meal", "પેટ્રોલ + જમવાનું", "inr"), ("Paid", "ચૂકવ્યું", "inr"), ("Due", "બાકી", "inr")],
                          rows, _sum_cols(rows, [1, 2, 3, 4, 5, 6, 7])))
    wage_stmt = select(LabourGroupWage)
    if grain_id:
        wage_stmt = wage_stmt.where(LabourGroupWage.grain_id == grain_id)
    wages = sorted((await db.scalars(wage_stmt)).unique().all(), key=lambda w: (w.labour_group.group_name, w.grain.grain_name))
    if wages:
        r.tables.append(Table(("Agreed wage rates (₹ per bag)", "નક્કી મજૂરી દર (₹ બેગ દીઠ)"), [("Group", "જૂથ", "text"), ("Grain", "અનાજ", "text"), ("Weighing", "તોલાઈ", "inr"), ("Loading", "લોડિંગ", "inr"),
                                                                                        ("Pulling", "ખેંચાઈ", "inr"), ("Mixing", "મિક્સિંગ", "inr"), ("Other", "અન્ય", "inr")],
                              [[w.labour_group.group_name, w.grain.grain_name, w.weighing_rate, w.loading_rate, w.pulling_rate, w.mixing_rate, w.other_expenses or 0] for w in wages]))
    r.bars.append(Bars(("Wages by month", "મહિના મુજબ મજૂરી"), monthly([(w.work_date, w.payable_amount) for w in works])))
    r.notes.append(("Labour work is not tied to a village or grain, so those filters do not apply here (the grain filter only narrows the wage-rate table).",
                    "મજૂર કામ ગામ કે અનાજ સાથે જોડાયેલું નથી, તેથી તે ફિલ્ટર અહીં લાગુ પડતા નથી (અનાજ ફિલ્ટર ફક્ત દર કોષ્ટક માટે)."))
    await _money_blocks(db, r, party_type="labour_group", year=year, party_ids=None)
    return r


# ---------------------------------------------------------------- bag suppliers

async def bag_report(db: AsyncSession, year: str, grain_id: int, village_id: int, today: date) -> Report:
    rows_ = [b for b in (await db.scalars(select(BagSupply).where(BagSupply.business_year == year))).unique().all()
             if not village_id or b.farmer.village_id == village_id]
    paid = await paid_map(db, "bag_supplier", [b.id for b in rows_])
    r = Report("bag_supplier")
    amount = sum(b.payable_amount for b in rows_)
    bags = sum(b.no_of_bags for b in rows_)
    paid_total = sum(paid.get(b.id, 0) for b in rows_)
    r.stats = [
        Stat("Supplies", "સપ્લાય", len(rows_), "int", f"{len({b.supplier_id for b in rows_})} suppliers"),
        Stat("Bags supplied", "આપેલી બેગ", bags, "int"),
        Stat("Amount", "રકમ", amount, "inr", f"avg ₹ {round(amount / bags, 2) if bags else 0} / bag"),
        Stat("Paid", "ચૂકવ્યું", paid_total, "inr", f"{pct(paid_total, amount) or 0}% of amount"),
        Stat("Due", "બાકી", amount - paid_total),
    ]
    g = _G()
    for b in rows_:
        x = g[b.supplier.pet_name]
        x["n"] += 1
        x["bags"] += b.no_of_bags
        x["amount"] += b.payable_amount
        x["paid"] += paid.get(b.id, 0)
    rows = sorted(([k, v["n"], v["bags"], round(v["amount"] / v["bags"], 2) if v["bags"] else 0, v["amount"], v["paid"], v["amount"] - v["paid"]] for k, v in g.items()), key=lambda x: -x[4])
    r.tables.append(Table(("By supplier", "સપ્લાયર મુજબ"), [("Supplier", "સપ્લાયર", "text"), ("Supplies", "સપ્લાય", "int"), ("Bags", "બેગ", "int"), ("Avg rate / bag", "સરેરાશ ભાવ / બેગ", "text"),
                                                         ("Amount", "રકમ", "inr"), ("Paid", "ચૂકવ્યું", "inr"), ("Due", "બાકી", "inr")], rows, _sum_cols(rows, [1, 2, 4, 5, 6])))
    v = _G()
    farmers_in: dict[str, set] = defaultdict(set)
    for b in rows_:
        name = b.farmer.village.village_name
        farmers_in[name].add(b.farmer_id)
        v[name]["bags"] += b.no_of_bags
        v[name]["amount"] += b.payable_amount
    rows = sorted(([k, len(farmers_in[k]), x["bags"], x["amount"]] for k, x in v.items()), key=lambda x: -x[2])
    r.tables.append(Table(("Bags held by village", "ગામ મુજબ સંગ્રહ"), [("Village", "ગામ", "text"), ("Storing farmers", "સંગ્રહ કરનાર ખેડૂત", "int"), ("Bags", "બેગ", "int"), ("Value", "કિંમત", "inr")],
                          rows, _sum_cols(rows, [1, 2, 3])))
    r.bars.append(Bars(("Bag cost by month", "મહિના મુજબ બારદાન ખર્ચ"), monthly([(b.supply_date, b.payable_amount) for b in rows_])))
    r.notes.append(("Bags are not tied to a grain, so the grain filter does not apply here.", "બારદાન અનાજ સાથે જોડાયેલા નથી, તેથી અનાજ ફિલ્ટર અહીં લાગુ પડતું નથી."))
    await _money_blocks(db, r, party_type="bag_supplier", year=year, party_ids={b.supplier_id for b in rows_} if village_id else None)
    return r


# ---------------------------------------------------------------- brokers

async def broker_report(db: AsyncSession, year: str, grain_id: int, village_id: int, today: date) -> Report:
    views = [v for v in await rec_svc.bilty_views(db, business_year=year) if _keep_trip(v.bilty.trip, grain_id, village_id)]
    bilties = [v.bilty for v in views]
    paid = await paid_map(db, "broker", [b.id for b in bilties])
    r = Report("broker")
    amount = sum(b.brokerage_amount for b in bilties)
    bags = sum(b.total_bags_in_truck for b in bilties)
    paid_total = sum(paid.get(b.id, 0) for b in bilties)
    r.stats = [
        Stat("Bilties", "બિલ્ટી", len(bilties), "int", f"{len({b.booking.brokerage.broker_id for b in bilties})} brokers"),
        Stat("Bags", "બેગ", bags, "int"),
        Stat("Brokerage", "દલાલી", amount, "inr", f"avg ₹ {round(amount / bags, 2) if bags else 0} / bag"),
        Stat("Paid", "ચૂકવ્યું", paid_total, "inr", f"{pct(paid_total, amount) or 0}% of brokerage"),
        Stat("Due", "બાકી", amount - paid_total),
    ]
    head = [("Bilties", "બિલ્ટી", "int"), ("Bags", "બેગ", "int"), ("Brokerage", "દલાલી", "inr"), ("Paid", "ચૂકવ્યું", "inr"), ("Due", "બાકી", "inr")]

    def grouped(key_fn, label_head, title):
        g = _G()
        for b in bilties:
            k = key_fn(b)
            g[k]["n"] += 1
            g[k]["bags"] += b.total_bags_in_truck
            g[k]["amount"] += b.brokerage_amount
            g[k]["paid"] += paid.get(b.id, 0)
        rows = sorted(([k, v["n"], v["bags"], v["amount"], v["paid"], v["amount"] - v["paid"]] for k, v in g.items()), key=lambda x: -x[3])
        r.tables.append(Table(title, [label_head, *head], rows, _sum_cols(rows, [1, 2, 3, 4, 5])))

    grouped(lambda b: b.booking.brokerage.broker.broker_name, ("Broker", "દલાલ", "text"), ("By broker", "દલાલ મુજબ"))
    grouped(lambda b: b.trip.industry.industrialist_name, ("Industry", "ઉદ્યોગ", "text"), ("By industry", "ઉદ્યોગ મુજબ"))
    grouped(lambda b: b.trip.grain.grain_name, ("Grain", "અનાજ", "text"), ("By grain", "અનાજ મુજબ"))
    r.bars.append(Bars(("Brokerage by month", "મહિના મુજબ દલાલી"), monthly([(b.bilty_date, b.brokerage_amount) for b in bilties])))
    await _money_blocks(db, r, party_type="broker", year=year, party_ids={b.booking.brokerage.broker_id for b in bilties} if (grain_id or village_id) else None)
    return r


# ---------------------------------------------------------------- industries (receipts)

async def industry_report(db: AsyncSession, year: str, grain_id: int, village_id: int, today: date) -> Report:
    views = [v for v in await rec_svc.bilty_views(db, business_year=year) if _keep_trip(v.bilty.trip, grain_id, village_id)]
    weighed = [v for v in views if v.receivable is not None]
    r = Report("industry")
    s = rec_svc.summarize(views)
    our_kg = sum(v.bilty.merchant_net_weight for v in weighed)
    r.stats = [
        Stat("Trucks billed", "બિલ થયેલી ટ્રક", len(views), "int", f"{s['awaiting_weight']} awaiting industry weight"),
        Stat("Billed", "બિલ", s["billed"], "inr", f"after deductions · {sum(v.bilty.booking.percentage_deduction and 1 or 0 for v in weighed)} trucks with a deduction"),
        Stat("Received", "મળ્યા", s["received"], "inr", f"{pct(s['received'], s['billed']) or 0}% of billed"),
        Stat("Outstanding", "બાકી", s["due"]),
        Stat("Weight shortage", "વજન ઘટ", s["short_kg"], "kg", f"{pct(s['short_kg'], our_kg) or 0}% of our weight"),
    ]
    g = _G()
    for v in views:
        b = v.bilty
        x = g[b.trip.industry.industrialist_name]
        x["trucks"] += 1
        x["awaiting"] += v.receivable is None
        if v.receivable is not None:
            x["our"] += b.merchant_net_weight
            x["short"] += -(b.difference_in_delivering_weight or 0)
            x["billed"] += v.receivable
            x["received"] += v.received
            x["due"] += max(v.due, 0)
    rows = sorted(([k, x["trucks"], x["awaiting"], x["our"], x["short"], pct(x["short"], x["our"]), x["billed"], x["received"], x["due"]] for k, x in g.items()), key=lambda y: -y[8])
    total = _sum_cols(rows, [1, 2, 3, 4, 6, 7, 8])
    if total:
        total[5] = pct(total[4], total[3])
    r.tables.append(Table(("By industry", "ઉદ્યોગ મુજબ"), [("Industry", "ઉદ્યોગ", "text"), ("Trucks", "ટ્રક", "int"), ("Awaiting weight", "વજન બાકી", "int"), ("Our kg", "આપણું કિલો", "kg"),
                                                          ("Shortage kg", "ઘટ કિલો", "kg"), ("Shortage %", "ઘટ %", "pct"), ("Billed", "બિલ", "inr"), ("Received", "મળ્યા", "inr"), ("Outstanding", "બાકી", "inr")],
                          rows, total))
    g = _G()
    for v in weighed:
        x = g[v.bilty.trip.grain.grain_name]
        x["trucks"] += 1
        x["billed"] += v.receivable
        x["received"] += v.received
        x["due"] += max(v.due, 0)
    rows = sorted(([k, x["trucks"], x["billed"], x["received"], x["due"]] for k, x in g.items()), key=lambda y: -y[2])
    r.tables.append(Table(("By grain (weighed trucks)", "અનાજ મુજબ (તોલાયેલી ટ્રક)"), [("Grain", "અનાજ", "text"), ("Trucks", "ટ્રક", "int"), ("Billed", "બિલ", "inr"), ("Received", "મળ્યા", "inr"), ("Outstanding", "બાકી", "inr")],
                          rows, _sum_cols(rows, [1, 2, 3, 4])))
    worst = sorted((v for v in weighed if v.bilty.percentage_difference is not None), key=lambda v: -v.bilty.percentage_difference)[:10]
    r.tables.append(Table(("Biggest weight shortages", "સૌથી મોટી વજન ઘટ"), [("Bill", "બિલ", "int"), ("Truck", "ટ્રક", "text"), ("Industry", "ઉદ્યોગ", "text"), ("Our kg", "આપણું કિલો", "kg"),
                                                                          ("Industry kg", "કારખાનું કિલો", "kg"), ("Shortage %", "ઘટ %", "pct")],
                          [[v.bilty.bill_number, v.bilty.trip.truck.truck_number, v.bilty.trip.industry.industrialist_name, v.bilty.merchant_net_weight, v.bilty.industry_net_weight,
                            v.bilty.percentage_difference] for v in worst]))
    r.bars.append(Bars(("Billed by month", "મહિના મુજબ બિલ"), monthly([(v.bilty.bilty_date, v.receivable) for v in weighed])))
    await _money_blocks(db, r, party_type=None, year=year, party_ids={v.bilty.trip.industry.id for v in views} if (grain_id or village_id) else None)
    return r


BUILDERS = {"farmer": farmer_report, "truck": truck_report, "labour_group": labour_report, "bag_supplier": bag_report, "broker": broker_report, "industry": industry_report}


async def build(db: AsyncSession, ledger: str, year: str, grain_id: int, village_id: int, today: date) -> Report:
    return await BUILDERS[ledger](db, year, grain_id, village_id, today)
