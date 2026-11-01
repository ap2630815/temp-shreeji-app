"""Bags bought per farmer entry (total_available_bags) minus the bags loaded on trucks and the bags taken to a stockyard.

A farmer entry is either a purchase_farmers_entries row (a purchase_group entry) or a purchase_individuals row; the helpers
below work on one kind at a time, picked by `individual`."""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FarmerStockyardTransfer, PurchaseFarmerEntry, PurchaseIndividual, FarmersTruckLoadLine


@dataclass
class Stock:
    bought: int = 0
    loaded: int = 0
    moved: int = 0  # taken from the farmer's place to a stockyard

    @property
    def available(self) -> int:
        return self.bought - self.loaded - self.moved


def _cols(individual: bool):
    """(entry model, load-line column, transfer column)."""
    if individual:
        return PurchaseIndividual, FarmersTruckLoadLine.purchase_individual_id, FarmerStockyardTransfer.purchase_individual_id
    return PurchaseFarmerEntry, FarmersTruckLoadLine.purchase_farmer_entry_id, FarmerStockyardTransfer.purchase_farmer_entry_id


async def stock_by_entry(db: AsyncSession, entry_ids: list[int] | None = None, exclude_trip_id: int | None = None,
                         individual: bool = False, exclude_transfer_id: int | None = None) -> dict[int, Stock]:
    """Per entry id. `exclude_trip_id` / `exclude_transfer_id` leave one trip's / one transfer's own bags out (when editing it)."""
    model, line_col, transfer_col = _cols(individual)
    bought_q = select(model.id, model.total_available_bags)
    loaded_q = select(line_col, func.sum(FarmersTruckLoadLine.no_of_loaded_bags)).where(line_col.is_not(None)).group_by(line_col)
    moved_q = select(transfer_col, func.sum(FarmerStockyardTransfer.no_of_bags)).where(transfer_col.is_not(None)).group_by(transfer_col)
    if entry_ids is not None:
        bought_q = bought_q.where(model.id.in_(entry_ids))
        loaded_q = loaded_q.where(line_col.in_(entry_ids))
        moved_q = moved_q.where(transfer_col.in_(entry_ids))
    if exclude_trip_id is not None:
        loaded_q = loaded_q.where(FarmersTruckLoadLine.trip_id != exclude_trip_id)
    if exclude_transfer_id is not None:
        moved_q = moved_q.where(FarmerStockyardTransfer.id != exclude_transfer_id)
    out: dict[int, Stock] = {}
    for eid, total in (await db.execute(bought_q)).all():
        out.setdefault(eid, Stock()).bought = int(total)
    for eid, total in (await db.execute(loaded_q)).all():
        out.setdefault(eid, Stock()).loaded = int(total)
    for eid, total in (await db.execute(moved_q)).all():
        out.setdefault(eid, Stock()).moved = int(total)
    return out


async def stock_by_purchase_group(db: AsyncSession, purchase_group_ids: list[int]) -> dict[int, Stock]:
    """Per purchase_group.id (one deal): bags bought across its entries vs bags loaded / moved from them."""
    bought_q = (
        select(PurchaseFarmerEntry.purchase_group_id, func.sum(PurchaseFarmerEntry.total_available_bags))
        .where(PurchaseFarmerEntry.purchase_group_id.in_(purchase_group_ids)).group_by(PurchaseFarmerEntry.purchase_group_id)
    )
    loaded_q = (
        select(PurchaseFarmerEntry.purchase_group_id, func.sum(FarmersTruckLoadLine.no_of_loaded_bags))
        .join(PurchaseFarmerEntry, PurchaseFarmerEntry.id == FarmersTruckLoadLine.purchase_farmer_entry_id)
        .where(PurchaseFarmerEntry.purchase_group_id.in_(purchase_group_ids)).group_by(PurchaseFarmerEntry.purchase_group_id)
    )
    moved_q = (
        select(PurchaseFarmerEntry.purchase_group_id, func.sum(FarmerStockyardTransfer.no_of_bags))
        .join(PurchaseFarmerEntry, PurchaseFarmerEntry.id == FarmerStockyardTransfer.purchase_farmer_entry_id)
        .where(PurchaseFarmerEntry.purchase_group_id.in_(purchase_group_ids)).group_by(PurchaseFarmerEntry.purchase_group_id)
    )
    out: dict[int, Stock] = {}
    for pid, total in (await db.execute(bought_q)).all():
        out.setdefault(pid, Stock()).bought = int(total)
    for pid, total in (await db.execute(loaded_q)).all():
        out.setdefault(pid, Stock()).loaded = int(total)
    for pid, total in (await db.execute(moved_q)).all():
        out.setdefault(pid, Stock()).moved = int(total)
    return out


async def renumber_remaining(db: AsyncSession, entry_id: int, individual: bool = False) -> None:
    """farmers_truck_load_lines.total_remaining_bags: bags still at the farmer right after each line (bought - taken to a stockyard -
    loaded so far), lines in id order. Called after any line or transfer of this entry is added, changed or removed."""
    model, line_col, transfer_col = _cols(individual)
    entry = await db.get(model, entry_id)
    lines = (await db.scalars(select(FarmersTruckLoadLine).where(line_col == entry_id).order_by(FarmersTruckLoadLine.id))).all()
    moved = int(await db.scalar(select(func.coalesce(func.sum(FarmerStockyardTransfer.no_of_bags), 0)).where(transfer_col == entry_id)))
    remaining = entry.total_available_bags - moved
    for line in lines:
        remaining -= line.no_of_loaded_bags
        line.total_remaining_bags = max(remaining, 0)
