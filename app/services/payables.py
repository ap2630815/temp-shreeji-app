"""One payment engine for every party we pay: farmers, trucks (owners), labour groups, bag suppliers, brokers.

Each party type exposes a list of Payable rows (what we owe and when). A payment is spread over them oldest-first and
recorded as allocations, so paid / due / status are always derived, never stored."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    BagSupplier,
    BagSupply,
    Bilty,
    Broker,
    BrokerBooking,
    Brokerage,
    Farmer,
    LabourGroup,
    LabourWork,
    Payment,
    PaymentAllocation,
    Truck,
    TruckTrip,
    User,
)
from app.services import audit
from app.services.ledger import DIRECT, FARMER, all_entry_views, allocate
from app.services.locks import advisory_lock
from app.services.years import assert_year_open


@dataclass(frozen=True)
class PartySpec:
    """party_type doubles as payment_allocations.payable_type (file5): farmer, truck, labour_group, bag_supplier, broker."""

    label: tuple[str, str]
    model: type
    name: Callable[[Any], str]
    name_gu: Callable[[Any], str | None]
    mobile: Callable[[Any], str]
    receiver: Callable[[Any], tuple[str, str]]  # default (name, mobile) of whoever collects the money


PARTIES: dict[str, PartySpec] = {
    "farmer": PartySpec(("Farmer", "ખેડૂત"), Farmer, lambda p: p.farmer_name, lambda p: p.farmer_name_gu, lambda p: p.mobile,
                        lambda p: (p.farmer_name if (p.head_of_family or "").lower() == "self" else (p.head_of_family or p.farmer_name), p.mobile)),
    "truck": PartySpec(("Truck", "ટ્રક"), Truck, lambda p: p.truck_number, lambda p: None, lambda p: p.truck_owner_mobile,
                       lambda p: (p.truck_owner_name, p.truck_owner_mobile)),  # paid to the truck owner
    "labour_group": PartySpec(("Labour", "મજૂર"), LabourGroup, lambda p: p.group_name, lambda p: p.group_name_gu, lambda p: "",
                              lambda p: (p.group_name, "")),
    "bag_supplier": PartySpec(("Bag supplier", "બારદાન સપ્લાયર"), BagSupplier, lambda p: p.pet_name, lambda p: p.name_gu, lambda p: p.mobile,
                              lambda p: (p.name, p.mobile)),
    "broker": PartySpec(("Broker", "દલાલ"), Broker, lambda p: p.broker_name, lambda p: p.broker_name_gu, lambda p: p.mobile,
                        lambda p: (p.broker_name, p.mobile)),
}


# statement columns after the date, per party type: (English, Gujarati, right-aligned); Payable.cells fills them in order
COLUMNS: dict[str, tuple[tuple[str, str, bool], ...]] = {
    "farmer": (("Details", "વિગત", False),),
    "truck": (("Industry", "ઉદ્યોગ", False), ("Grain", "અનાજ", False), ("Bags", "બેગ", True)),
    "labour_group": (("Work", "કામ", False),),
    "bag_supplier": (("Farmer", "ખેડૂત", False), ("Village", "ગામ", False), ("Bags", "બેગ", True), ("Rate/bag", "ભાવ/બેગ", True)),
    "broker": (("Bill no.", "બિલ નં.", False), ("Truck", "ટ્રક", False), ("Industry", "ઉદ્યોગ", False)),
}


class PaymentError(Exception):
    def __init__(self, field: str, message: tuple[str, str]):
        self.field, self.message = field, message
        super().__init__(message[0])


@dataclass
class Payable:
    payable_type: str
    payable_id: int
    party_type: str
    party_id: int
    party_name: str
    doc_date: date
    due_date: date | None  # only farmers have an agreed pay-after date
    label: str
    amount: int
    paid: int
    cells: tuple = ()  # the type-specific columns of COLUMNS[party_type], for the statement table

    @property
    def due(self) -> int:
        return self.amount - self.paid

    @property
    def status(self) -> str:
        if self.due <= 0:
            return "paid"
        return "partial" if self.paid > 0 else "pending"

    def is_overdue(self, today: date) -> bool:
        return self.due > 0 and self.due_date is not None and self.due_date < today

    @property
    def sort_key(self) -> tuple:
        return (self.due_date or self.doc_date, self.doc_date, self.payable_type, self.payable_id)


async def _paid_map(db: AsyncSession, payable_type: str, ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    rows = await db.execute(
        select(PaymentAllocation.payable_id, func.sum(PaymentAllocation.amount))
        .where(PaymentAllocation.payable_type == payable_type, PaymentAllocation.payable_id.in_(ids))
        .group_by(PaymentAllocation.payable_id)
    )
    return {pid: int(total) for pid, total in rows.all()}


paid_map = _paid_map  # public alias for reports


async def load_payables(db: AsyncSession, party_type: str, party_id: int | None = None) -> list[Payable]:
    """Everything we owe (or have owed) to one party, or to all parties of a type when party_id is None."""
    pt = party_type  # allocation payable_type
    out: list[Payable] = []

    if party_type == "farmer":
        for v in await all_entry_views(db, farmer_id=party_id):  # purchase entries and direct entries
            e = v.entry
            source = "direct" if e.is_direct else f"#{e.purchase_group_id}, {e.purchase_group.purchase_group_date}"
            out.append(Payable(DIRECT if e.is_direct else FARMER, e.id, party_type, e.farmer_id, e.farmer.farmer_name, e.entry_date, e.due_date,
                               f"{e.farmer.village.village_name} · {e.grain.grain_name} ({source}), {e.no_of_filled_bags} bags", e.net_payable, v.paid,
                               (f"{e.farmer.village.village_name} · {e.grain.grain_name} ({source}), {e.no_of_filled_bags} bags",)))
    elif party_type == "truck":
        stmt = select(TruckTrip).order_by(TruckTrip.trip_date, TruckTrip.id)
        if party_id:
            stmt = stmt.where(TruckTrip.truck_id == party_id)
        trips = list((await db.scalars(stmt)).unique().all())
        paid = await _paid_map(db, pt, [t.id for t in trips])
        for t in trips:
            out.append(Payable(pt, t.id, party_type, t.truck_id, t.truck.truck_number, t.trip_date, None,
                               f"{t.truck.truck_number} → {t.industry.industrialist_name}, {t.grain.grain_name}, {t.bags} bags", t.total_amount, paid.get(t.id, 0),
                               (t.industry.industrialist_name, t.grain.grain_name, t.bags)))
    elif party_type == "labour_group":
        stmt = select(LabourWork).order_by(LabourWork.work_date, LabourWork.id)
        if party_id:
            stmt = stmt.where(LabourWork.labour_group_id == party_id)
        rows = list((await db.scalars(stmt)).unique().all())
        paid = await _paid_map(db, pt, [r.id for r in rows])
        for r in rows:
            out.append(Payable(pt, r.id, party_type, r.labour_group_id, r.labour_group.group_name, r.work_date, None,
                               r.description or "Labour work", r.net_payable, paid.get(r.id, 0),
                               (r.description or "Labour work",)))
    elif party_type == "bag_supplier":
        stmt = select(BagSupply).order_by(BagSupply.supply_date, BagSupply.id)
        if party_id:
            stmt = stmt.where(BagSupply.supplier_id == party_id)
        rows = list((await db.scalars(stmt)).unique().all())
        paid = await _paid_map(db, pt, [r.id for r in rows])
        for r in rows:
            out.append(Payable(pt, r.id, party_type, r.supplier_id, r.supplier.pet_name, r.supply_date, None,
                               f"{r.no_of_bags} bags @ ₹ {r.rate_per_bag} to {r.farmer.farmer_name} ({r.farmer.village.village_name})", r.payable_amount, paid.get(r.id, 0),
                               (r.farmer.farmer_name, r.farmer.village.village_name, r.no_of_bags, r.rate_per_bag)))
    elif party_type == "broker":
        stmt = (
            select(Bilty)
            .join(TruckTrip, TruckTrip.id == Bilty.truck_trip_id)
            .join(BrokerBooking, BrokerBooking.id == TruckTrip.broker_booking_id)
            .join(Brokerage, Brokerage.id == BrokerBooking.brokerage_id)
            .order_by(Bilty.bilty_date, Bilty.id)
        )
        if party_id:
            stmt = stmt.where(Brokerage.broker_id == party_id)
        rows = list((await db.scalars(stmt)).unique().all())
        paid = await _paid_map(db, pt, [r.id for r in rows])
        for r in rows:
            broker = r.booking.brokerage.broker
            out.append(Payable(pt, r.id, party_type, broker.id, broker.broker_name, r.bilty_date, None,
                               f"Bill #{r.bill_number}, {r.trip.truck.truck_number} → {r.trip.industry.industrialist_name}", r.brokerage_amount, paid.get(r.id, 0),
                               (f"#{r.bill_number}", r.trip.truck.truck_number, r.trip.industry.industrialist_name)))
    out.sort(key=lambda p: p.sort_key)
    return out


async def get_party(db: AsyncSession, party_type: str, party_id: int):
    spec = PARTIES.get(party_type)
    return None if spec is None else await db.get(spec.model, party_id)


def summarize(payables: list[Payable], today: date) -> dict[str, int]:
    return dict(
        count=sum(1 for p in payables if p.due > 0),
        amount=sum(p.amount for p in payables),
        paid=sum(p.paid for p in payables),
        due=sum(max(p.due, 0) for p in payables),
        overdue=sum(max(p.due, 0) for p in payables if p.is_overdue(today)),
    )


async def paid_for(db: AsyncSession, payable_type: str, payable_id: int) -> int:
    return (await _paid_map(db, payable_type, [payable_id])).get(payable_id, 0)


async def lock_party(db: AsyncSession, party_type: str, party_id: int) -> None:
    """Serialise concurrent payments to one party so two clerks cannot allocate against the same dues."""
    await advisory_lock(db, f"pay:{party_type}", party_id)


async def record_payment(db: AsyncSession, user: User, party_type: str, party_id: int, data: dict) -> Payment:
    """Allocate `data['amount']` oldest-first and add the payment. Raises YearLockedError or PaymentError. Caller commits.

    payments.status: 'partial' while the party still owes something afterwards; when this payment clears everything it is
    'complete' if it is the only payment, otherwise 'final' (the last of several partial payments)."""
    year = await assert_year_open(db, data["payment_date"])
    await lock_party(db, party_type, party_id)
    payables = await load_payables(db, party_type, party_id)
    outstanding = sum(max(p.due, 0) for p in payables)
    try:
        plan = allocate(data["amount"], [((p.payable_type, p.payable_id), p.due) for p in payables])  # (type, id): two tables can share an id
    except ValueError:
        raise PaymentError("amount", (f"Exceeds the outstanding amount (₹ {outstanding})", f"બાકી રકમ (₹ {outstanding}) થી વધુ")) from None
    earlier = int(await db.scalar(select(func.count()).select_from(Payment).where(Payment.party_type == party_type, Payment.party_id == party_id)))
    status = "partial" if data["amount"] < outstanding else ("final" if earlier else "complete")
    payment = Payment(party_type=party_type, party_id=party_id, business_year=year, status=status, created_by=user.id, **data)
    db.add(payment)
    await db.flush()
    db.add_all(PaymentAllocation(payment_id=payment.id, payable_type=ptype, payable_id=pid, amount=amt) for (ptype, pid), amt in plan)
    audit.log(db, user, "create", "payments", payment.id, dict(
        party=party_type, party_id=party_id, amount=data["amount"], method=data["method"], receiver=data["receiver_name"], status=status,
        allocations=[[ptype, pid, amt] for (ptype, pid), amt in plan]))
    return payment


async def payments_of(db: AsyncSession, party_type: str, party_id: int) -> list[Payment]:
    stmt = select(Payment).where(Payment.party_type == party_type, Payment.party_id == party_id).order_by(Payment.payment_date, Payment.id)
    return list((await db.scalars(stmt)).all())


async def payment_lines(db: AsyncSession, payment: Payment) -> list[dict]:
    """What a payment settled, and what each of those items still owed right after it (payments up to and including it)."""
    by_key = {(p.payable_type, p.payable_id): p for p in await load_payables(db, payment.party_type, payment.party_id)}
    types = {a.payable_type for a in payment.allocations}
    ids = [a.payable_id for a in payment.allocations]
    rows = await db.execute(
        select(PaymentAllocation.payable_type, PaymentAllocation.payable_id, func.sum(PaymentAllocation.amount))
        .where(PaymentAllocation.payable_type.in_(types), PaymentAllocation.payable_id.in_(ids), PaymentAllocation.payment_id <= payment.id)
        .group_by(PaymentAllocation.payable_type, PaymentAllocation.payable_id)
    )
    upto = {(ptype, pid): int(total) for ptype, pid, total in rows.all()}
    out = []
    for a in payment.allocations:
        key = (a.payable_type, a.payable_id)
        out.append(dict(payable=by_key[key], amount=a.amount, remaining=by_key[key].amount - upto[key]))
    return out
