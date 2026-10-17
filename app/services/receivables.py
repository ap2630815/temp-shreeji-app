"""Money coming in from industries: receivable per bilty (derived from the industry's weight), receipts, allocation."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Bilty, BrokerBooking, Receipt, ReceiptAllocation, TruckTrip, User
from app.services import audit
from app.services.ledger import allocate
from app.services.locks import advisory_lock
from app.services.payables import PaymentError
from app.services.years import assert_year_open


@dataclass
class BiltyView:
    bilty: Bilty
    received: int

    @property
    def receivable(self) -> int | None:
        """What the industry is billed: the weight-based receivable after the booking's percentage deduction."""
        return self.bilty.receivable_after_deduction

    @property
    def due(self) -> int | None:
        return None if self.receivable is None else self.receivable - self.received

    @property
    def status(self) -> str:
        if self.receivable is None:
            return "unweighed"
        if self.due <= 0:
            return "paid"
        return "partial" if self.received > 0 else "pending"


async def received_map(db: AsyncSession, bilty_ids: list[int]) -> dict[int, int]:
    if not bilty_ids:
        return {}
    rows = await db.execute(
        select(ReceiptAllocation.bilty_id, func.sum(ReceiptAllocation.amount))
        .where(ReceiptAllocation.bilty_id.in_(bilty_ids)).group_by(ReceiptAllocation.bilty_id)
    )
    return {bid: int(total) for bid, total in rows.all()}


async def bilty_views(db: AsyncSession, industry_id: int | None = None, business_year: str | None = None) -> list[BiltyView]:
    stmt = (
        select(Bilty)
        .join(TruckTrip, TruckTrip.id == Bilty.truck_trip_id)
        .join(BrokerBooking, BrokerBooking.id == TruckTrip.broker_booking_id)
        .order_by(Bilty.bilty_date, Bilty.id)
    )
    if industry_id is not None:
        stmt = stmt.where(BrokerBooking.industry_id == industry_id)
    if business_year is not None:
        stmt = stmt.where(Bilty.business_year == business_year)
    bilties = list((await db.scalars(stmt)).unique().all())
    received = await received_map(db, [b.id for b in bilties])
    return [BiltyView(b, received.get(b.id, 0)) for b in bilties]


def summarize(views: list[BiltyView]) -> dict[str, int]:
    weighed = [v for v in views if v.receivable is not None]
    return dict(
        trucks=len(views),
        awaiting_weight=len(views) - len(weighed),
        billed=sum(v.receivable for v in weighed),
        received=sum(v.received for v in views),
        due=sum(max(v.due, 0) for v in weighed),
        short_kg=sum(-(v.bilty.difference_in_delivering_weight or 0) for v in weighed),
    )


async def receipts_of(db: AsyncSession, industry_id: int) -> list[Receipt]:
    stmt = select(Receipt).where(Receipt.industry_id == industry_id).order_by(Receipt.receipt_date, Receipt.id)
    return list((await db.scalars(stmt)).unique().all())


async def record_receipt(db: AsyncSession, user: User, industry_id: int, data: dict) -> Receipt:
    """Allocate a receipt oldest-bilty-first over weighed bilties. Raises YearLockedError or PaymentError. Caller commits."""
    year = await assert_year_open(db, data["receipt_date"])
    await advisory_lock(db, "receive", industry_id)
    views = await bilty_views(db, industry_id)
    open_views = [v for v in views if v.due is not None]
    outstanding = sum(max(v.due, 0) for v in open_views)
    try:
        plan = allocate(data["amount"], [(v.bilty.id, v.due) for v in open_views])
    except ValueError:
        waiting = sum(1 for v in views if v.receivable is None)
        hint = (f" ({waiting} truck(s) still need the industry weight)", f" ({waiting} ટ્રકનું કારખાનાનું વજન બાકી)") if waiting else ("", "")
        raise PaymentError("amount", (f"Exceeds the outstanding receivable (₹ {outstanding}){hint[0]}", f"બાકી લેણાં (₹ {outstanding}) થી વધુ{hint[1]}")) from None
    receipt = Receipt(industry_id=industry_id, business_year=year, created_by=user.id, **data)
    db.add(receipt)
    await db.flush()
    db.add_all(ReceiptAllocation(receipt_id=receipt.id, bilty_id=bid, amount=amt) for bid, amt in plan)
    audit.log(db, user, "create", "receipts", receipt.id, dict(
        industry_id=industry_id, amount=data["amount"], method=data["method"], allocations=[[bid, amt] for bid, amt in plan]))
    return receipt
