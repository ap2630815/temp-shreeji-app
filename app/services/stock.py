"""Bags bought per commencing minus bags already loaded on trucks."""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PurchaseEntry, TruckLoadLine


@dataclass
class Stock:
    bought: int = 0
    loaded: int = 0

    @property
    def available(self) -> int:
        return self.bought - self.loaded


async def stock_by_commencing(db: AsyncSession, commencing_ids: list[int] | None = None, exclude_trip_id: int | None = None) -> dict[int, Stock]:
    bought_q = select(PurchaseEntry.commencing_id, func.sum(PurchaseEntry.filled_bags)).group_by(PurchaseEntry.commencing_id)
    loaded_q = select(TruckLoadLine.commencing_id, func.sum(TruckLoadLine.bags)).group_by(TruckLoadLine.commencing_id)
    if commencing_ids is not None:
        bought_q = bought_q.where(PurchaseEntry.commencing_id.in_(commencing_ids))
        loaded_q = loaded_q.where(TruckLoadLine.commencing_id.in_(commencing_ids))
    if exclude_trip_id is not None:
        loaded_q = loaded_q.where(TruckLoadLine.trip_id != exclude_trip_id)
    out: dict[int, Stock] = {}
    for cid, total in (await db.execute(bought_q)).all():
        out.setdefault(cid, Stock()).bought = int(total)
    for cid, total in (await db.execute(loaded_q)).all():
        out.setdefault(cid, Stock()).loaded = int(total)
    return out
