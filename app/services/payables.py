"""One payment engine for every party we pay: farmers, transporters, labour groups, bag suppliers, brokers.

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
    Farmer,
    LabourGroup,
    LabourWork,
    Payment,
    PaymentAllocation,
    Transporter,
    TruckTrip,
    User,
)
from app.services import audit
from app.services.ledger import allocate, entry_views
from app.services.locks import advisory_lock
from app.services.years import assert_year_open


@dataclass(frozen=True)
class PartySpec:
    label: tuple[str, str]
    model: type
    payable_type: str
    name: Callable[[Any], str]
    receiver: Callable[[Any], tuple[str, str]]  # default (name, mobile) of whoever collects the money


PARTIES: dict[str, PartySpec] = {
    "farmer": PartySpec(("Farmer", "ખેડૂત"), Farmer, "purchase_entry", lambda p: p.name, lambda p: (p.head_of_family or p.name, p.mobile)),
    "transporter": PartySpec(("Transport", "ટ્રાન્સપોર્ટ"), Transporter, "truck_trip", lambda p: p.pet_name, lambda p: (p.owner_name, p.mobile)),
    "labour": PartySpec(("Labour", "મજૂર"), LabourGroup, "labour_work", lambda p: p.group_name, lambda p: (p.name, p.mobile)),
    "bag_supplier": PartySpec(("Bag supplier", "બારદાન સપ્લાયર"), BagSupplier, "bag_supply", lambda p: p.pet_name, lambda p: (p.name, p.mobile)),
    "broker": PartySpec(("Broker", "દલાલ"), Broker, "bilty_brokerage", lambda p: p.name, lambda p: (p.name, p.mobile)),
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
        return (self.due_date or self.doc_date, self.doc_date, self.payable_id)


async def _paid_map(db: AsyncSession, payable_type: str, ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    rows = await db.execute(
        select(PaymentAllocation.payable_id, func.sum(PaymentAllocation.amount))
        .where(PaymentAllocation.payable_type == payable_type, PaymentAllocation.payable_id.in_(ids))
        .group_by(PaymentAllocation.payable_id)
    )
    return {pid: int(total) for pid, total in rows.all()}


async def load_payables(db: AsyncSession, party_type: str, party_id: int | None = None) -> list[Payable]:
    """Everything we owe (or have owed) to one party, or to all parties of a type when party_id is None."""
    spec = PARTIES[party_type]
    pt = spec.payable_type
    out: list[Payable] = []

    if party_type == "farmer":
        for v in await entry_views(db, farmer_id=party_id):
            e = v.entry
            out.append(Payable(pt, e.id, party_type, e.farmer_id, e.farmer.name, e.entry_date, e.due_date,
                               f"{e.commencing.village} · {e.commencing.grain.name}, {e.filled_bags} bags", e.net_payable, v.paid))
    elif party_type == "transporter":
        stmt = select(TruckTrip).order_by(TruckTrip.trip_date, TruckTrip.id)
        if party_id:
            stmt = stmt.where(TruckTrip.transport_id == party_id)
        trips = list((await db.scalars(stmt)).unique().all())
        paid = await _paid_map(db, pt, [t.id for t in trips])
        for t in trips:
            out.append(Payable(pt, t.id, party_type, t.transport_id, t.transport.pet_name, t.trip_date, None,
                               f"{t.truck.truck_number} → {t.industry.name}, {t.grain.name}, {t.bags} bags", t.final_payment, paid.get(t.id, 0)))
    elif party_type == "labour":
        stmt = select(LabourWork).order_by(LabourWork.work_date, LabourWork.id)
        if party_id:
            stmt = stmt.where(LabourWork.labour_group_id == party_id)
        rows = list((await db.scalars(stmt)).unique().all())
        paid = await _paid_map(db, pt, [r.id for r in rows])
        for r in rows:
            out.append(Payable(pt, r.id, party_type, r.labour_group_id, r.labour_group.group_name, r.work_date, None,
                               r.description or "Labour work", r.net_payable, paid.get(r.id, 0)))
    elif party_type == "bag_supplier":
        stmt = select(BagSupply).order_by(BagSupply.supply_date, BagSupply.id)
        if party_id:
            stmt = stmt.where(BagSupply.supplier_id == party_id)
        rows = list((await db.scalars(stmt)).unique().all())
        paid = await _paid_map(db, pt, [r.id for r in rows])
        for r in rows:
            out.append(Payable(pt, r.id, party_type, r.supplier_id, r.supplier.pet_name, r.supply_date, None,
                               f"{r.units} bags @ ₹{r.rate} to {r.farmer.name} ({r.farmer.village})", r.payable_amount, paid.get(r.id, 0)))
    elif party_type == "broker":
        stmt = select(Bilty).order_by(Bilty.bilty_date, Bilty.id)
        if party_id:
            stmt = stmt.where(Bilty.broker_id == party_id)
        rows = list((await db.scalars(stmt)).unique().all())
        paid = await _paid_map(db, pt, [r.id for r in rows])
        for r in rows:
            out.append(Payable(pt, r.id, party_type, r.broker_id, r.broker.name, r.bilty_date, None,
                               f"Bill #{r.bill_number}, {r.trip.truck.truck_number} → {r.trip.industry.name}", r.brokerage_amount, paid.get(r.id, 0)))
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
    """Allocate `data['amount']` oldest-first and add the payment. Raises YearLockedError or PaymentError. Caller commits."""
    year = await assert_year_open(db, data["payment_date"])
    await lock_party(db, party_type, party_id)
    payables = await load_payables(db, party_type, party_id)
    outstanding = sum(max(p.due, 0) for p in payables)
    try:
        plan = allocate(data["amount"], [(p.payable_id, p.due) for p in payables])
    except ValueError:
        raise PaymentError("amount", (f"Exceeds the outstanding amount (₹{outstanding})", f"બાકી રકમ (₹{outstanding}) થી વધુ")) from None
    payment = Payment(party_type=party_type, party_id=party_id, business_year=year, created_by=user.id, **data)
    db.add(payment)
    await db.flush()
    db.add_all(PaymentAllocation(payment_id=payment.id, payable_type=PARTIES[party_type].payable_type, payable_id=pid, amount=amt) for pid, amt in plan)
    audit.log(db, user, "create", "payments", payment.id, dict(
        party=party_type, party_id=party_id, amount=data["amount"], method=data["method"], receiver=data["receiver_name"],
        allocations=[[pid, amt] for pid, amt in plan]))
    return payment


async def payments_of(db: AsyncSession, party_type: str, party_id: int) -> list[Payment]:
    stmt = select(Payment).where(Payment.party_type == party_type, Payment.party_id == party_id).order_by(Payment.payment_date, Payment.id)
    return list((await db.scalars(stmt)).all())


async def payment_lines(db: AsyncSession, payment: Payment) -> list[dict]:
    """What a payment settled, and what each of those items still owed right after it (payments up to and including it)."""
    by_id = {p.payable_id: p for p in await load_payables(db, payment.party_type, payment.party_id)}
    ids = [a.payable_id for a in payment.allocations]
    pt = PARTIES[payment.party_type].payable_type
    rows = await db.execute(
        select(PaymentAllocation.payable_id, func.sum(PaymentAllocation.amount))
        .where(PaymentAllocation.payable_type == pt, PaymentAllocation.payable_id.in_(ids), PaymentAllocation.payment_id <= payment.id)
        .group_by(PaymentAllocation.payable_id)
    )
    upto = {pid: int(total) for pid, total in rows.all()}
    return [dict(payable=by_id[a.payable_id], amount=a.amount, remaining=by_id[a.payable_id].amount - upto[a.payable_id]) for a in payment.allocations]
