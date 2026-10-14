"""Bags bought per farmer entry (total_available_bags) minus bags already loaded on trucks."""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PurchaseFarmerEntry, TruckLoadLine


@dataclass
class Stock:
    bought: int = 0
    loaded: int = 0

    @property
    def available(self) -> int:
        return self.bought - self.loaded


async def stock_by_entry(db: AsyncSession, entry_ids: list[int] | None = None, exclude_trip_id: int | None = None) -> dict[int, Stock]:
    """Per purchase_farmer_entries.id. `exclude_trip_id` leaves one trip's own lines out (when editing that trip)."""
    bought_q = select(PurchaseFarmerEntry.id, PurchaseFarmerEntry.total_available_bags)
    loaded_q = select(TruckLoadLine.purchase_farmer_entry_id, func.sum(TruckLoadLine.no_of_loaded_bags)).group_by(TruckLoadLine.purchase_farmer_entry_id)
    if entry_ids is not None:
        bought_q = bought_q.where(PurchaseFarmerEntry.id.in_(entry_ids))
        loaded_q = loaded_q.where(TruckLoadLine.purchase_farmer_entry_id.in_(entry_ids))
    if exclude_trip_id is not None:
        loaded_q = loaded_q.where(TruckLoadLine.trip_id != exclude_trip_id)
    out: dict[int, Stock] = {}
    for eid, total in (await db.execute(bought_q)).all():
        out.setdefault(eid, Stock()).bought = int(total)
    for eid, total in (await db.execute(loaded_q)).all():
        out.setdefault(eid, Stock()).loaded = int(total)
    return out


async def stock_by_purchase_info(db: AsyncSession, purchase_info_ids: list[int]) -> dict[int, Stock]:
    """Per purchase_info.id (a village deal): bags bought across its entries vs bags loaded from them."""
    bought_q = (
        select(PurchaseFarmerEntry.purchase_info_id, func.sum(PurchaseFarmerEntry.total_available_bags))
        .where(PurchaseFarmerEntry.purchase_info_id.in_(purchase_info_ids)).group_by(PurchaseFarmerEntry.purchase_info_id)
    )
    loaded_q = (
        select(PurchaseFarmerEntry.purchase_info_id, func.sum(TruckLoadLine.no_of_loaded_bags))
        .join(PurchaseFarmerEntry, PurchaseFarmerEntry.id == TruckLoadLine.purchase_farmer_entry_id)
        .where(PurchaseFarmerEntry.purchase_info_id.in_(purchase_info_ids)).group_by(PurchaseFarmerEntry.purchase_info_id)
    )
    out: dict[int, Stock] = {}
    for pid, total in (await db.execute(bought_q)).all():
        out.setdefault(pid, Stock()).bought = int(total)
    for pid, total in (await db.execute(loaded_q)).all():
        out.setdefault(pid, Stock()).loaded = int(total)
    return out


async def renumber_remaining(db: AsyncSession, entry_id: int) -> None:
    """truck_load_lines.total_remaining_bags: bags still unloaded in the entry right after each line, lines in id order.
    Called after any line of this entry is added, changed or removed."""
    entry = await db.get(PurchaseFarmerEntry, entry_id)
    lines = (await db.scalars(select(TruckLoadLine).where(TruckLoadLine.purchase_farmer_entry_id == entry_id).order_by(TruckLoadLine.id))).all()
    remaining = entry.total_available_bags
    for line in lines:
        remaining -= line.no_of_loaded_bags
        line.total_remaining_bags = remaining
