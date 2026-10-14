"""Derived money state. Paid/due/status come from allocations, never from stored totals."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PaymentAllocation, PurchaseFarmerEntry

FARMER = "farmer"  # payments.party_type / payment_allocations.payable_type for farmers


@dataclass
class EntryView:
    entry: PurchaseFarmerEntry
    paid: int

    @property
    def net_payable(self) -> int:
        return self.entry.net_payable

    @property
    def due(self) -> int:
        return self.net_payable - self.paid

    @property
    def status(self) -> str:
        if self.due <= 0:
            return "paid"
        return "partial" if self.paid > 0 else "pending"

    def is_overdue(self, today: date) -> bool:
        return self.due > 0 and self.entry.due_date < today


def allocate(amount: int, dues: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Spread `amount` over (payable_id, due) pairs in the given order (oldest due first). Pure function.

    Raises ValueError if the amount is not positive or exceeds the total outstanding."""
    if amount <= 0:
        raise ValueError("amount must be positive")
    remaining = amount
    out: list[tuple[int, int]] = []
    for payable_id, due in dues:
        if remaining == 0:
            break
        if due <= 0:
            continue
        take = min(due, remaining)
        out.append((payable_id, take))
        remaining -= take
    if remaining:
        raise ValueError("amount exceeds outstanding")
    return out


def _paid_subquery():
    return (
        select(PaymentAllocation.payable_id.label("entry_id"), func.sum(PaymentAllocation.amount).label("paid"))
        .where(PaymentAllocation.payable_type == FARMER)
        .group_by(PaymentAllocation.payable_id)
        .subquery()
    )


async def entry_views(
    db: AsyncSession, *, purchase_info_ids: list[int] | None = None, farmer_id: int | None = None
) -> list[EntryView]:
    paid = _paid_subquery()
    stmt = (
        select(PurchaseFarmerEntry, func.coalesce(paid.c.paid, 0))
        .outerjoin(paid, paid.c.entry_id == PurchaseFarmerEntry.id)
        .order_by(PurchaseFarmerEntry.due_date, PurchaseFarmerEntry.id)
    )
    if purchase_info_ids is not None:
        stmt = stmt.where(PurchaseFarmerEntry.purchase_info_id.in_(purchase_info_ids))
    if farmer_id is not None:
        stmt = stmt.where(PurchaseFarmerEntry.farmer_id == farmer_id)
    return [EntryView(e, int(p)) for e, p in (await db.execute(stmt)).unique().all()]


async def paid_for_entry(db: AsyncSession, entry_id: int) -> int:
    return int(
        await db.scalar(
            select(func.coalesce(func.sum(PaymentAllocation.amount), 0)).where(
                PaymentAllocation.payable_type == FARMER, PaymentAllocation.payable_id == entry_id
            )
        )
    )


async def purchase_info_entries(db: AsyncSession, purchase_info_id: int) -> list[EntryView]:
    return await entry_views(db, purchase_info_ids=[purchase_info_id])


def totals(views: list[EntryView], today: date) -> dict[str, int]:
    return dict(
        farmers=len({v.entry.farmer_id for v in views}),
        bags=sum(v.entry.no_of_filled_bags for v in views),
        handful=sum(v.entry.no_of_handful_bags for v in views),
        kilos=sum(v.entry.extra_kilos for v in views),
        net_payable=sum(v.net_payable for v in views),
        paid=sum(v.paid for v in views),
        due=sum(max(v.due, 0) for v in views),
        overdue=sum(max(v.due, 0) for v in views if v.is_overdue(today)),
    )
