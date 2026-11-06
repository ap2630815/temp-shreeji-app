"""Stockyard bag ledgers, per stockyard and grain. Nothing is stored: every figure is worked out from the records.

Filled bags   in  = stockyard purchase entries (no_of_filled_bags) + farmer_stockyard_transfers (bags brought from a farmer's place)
              out = stockyard_truck_load_lines (bags loaded on a truck)
Empty bags    in  = empty_bags (bought into the stockyard) + no_of_received_empty_bags of the purchase entries (returned by the farmer)
              out = no_of_given_empty_bags of the stockyard purchases (handed to the farmer to fill)
              error (information only, not in the balance) = per purchase: given - filled bags of its entries - received"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    BrokerBooking, Brokerage, FarmerStockyardTransfer, TruckTrip, PurchaseFarmerEntry, PurchaseGroup, PurchaseIndividual, EmptyBag, StockyardTruckLoadLine,
    StockyardPurchase, StockyardPurchaseEntry,
)

Key = tuple[int, int]  # (stockyard_id, grain_id)


@dataclass
class Filled:
    purchased: int = 0
    from_farmers: int = 0
    loaded: int = 0

    @property
    def balance(self) -> int:
        return self.purchased + self.from_farmers - self.loaded


@dataclass
class Empty:
    bought: int = 0
    given: int = 0     # handed out on stockyard purchases
    received: int = 0  # returned by the farmer on purchase entries
    error: int = 0     # given - filled - received, summed per purchase

    @property
    def balance(self) -> int:
        return self.bought - self.given + self.received


def default_received(given: int, filled_all_entries: int, received_other_entries: int) -> int:
    """Empty bags a purchase entry gets back by default: what was given, less every filled bag of the purchase, less what other entries already returned.
    Below zero means the farmer needed more empty bags than were given: the purchase's given bags must be raised."""
    return given - filled_all_entries - received_other_entries


async def filled_ledger(db: AsyncSession, stockyard_id: int | None = None, grain_id: int | None = None) -> dict[Key, Filled]:
    out: dict[Key, Filled] = {}

    def keep(q, stockyard_col, grain_col):
        if stockyard_id is not None:
            q = q.where(stockyard_col == stockyard_id)
        if grain_id is not None:
            q = q.where(grain_col == grain_id)
        return q

    bought = keep(
        select(StockyardPurchase.stockyard_id, StockyardPurchase.grain_id, func.sum(StockyardPurchaseEntry.no_of_filled_bags))
        .join(StockyardPurchase, StockyardPurchase.id == StockyardPurchaseEntry.stockyard_purchase_id)
        .group_by(StockyardPurchase.stockyard_id, StockyardPurchase.grain_id), StockyardPurchase.stockyard_id, StockyardPurchase.grain_id)
    for sy, gr, n in (await db.execute(bought)).all():
        out.setdefault((sy, gr), Filled()).purchased = int(n)

    from_group = keep(
        select(FarmerStockyardTransfer.stockyard_id, PurchaseGroup.grain_id, func.sum(FarmerStockyardTransfer.no_of_transferred_bags))
        .join(PurchaseFarmerEntry, PurchaseFarmerEntry.id == FarmerStockyardTransfer.purchase_farmer_entry_id)
        .join(PurchaseGroup, PurchaseGroup.id == PurchaseFarmerEntry.purchase_group_id)
        .group_by(FarmerStockyardTransfer.stockyard_id, PurchaseGroup.grain_id), FarmerStockyardTransfer.stockyard_id, PurchaseGroup.grain_id)
    from_individual = keep(
        select(FarmerStockyardTransfer.stockyard_id, PurchaseIndividual.grain_id, func.sum(FarmerStockyardTransfer.no_of_transferred_bags))
        .join(PurchaseIndividual, PurchaseIndividual.id == FarmerStockyardTransfer.purchase_individual_id)
        .group_by(FarmerStockyardTransfer.stockyard_id, PurchaseIndividual.grain_id), FarmerStockyardTransfer.stockyard_id, PurchaseIndividual.grain_id)
    for q in (from_group, from_individual):
        for sy, gr, n in (await db.execute(q)).all():
            out.setdefault((sy, gr), Filled()).from_farmers += int(n)

    # a line has no grain of its own: it is the grain of its trip's booking (trip -> booking -> brokerage -> grain)
    loaded = keep(
        select(StockyardTruckLoadLine.stockyard_id, Brokerage.grain_id, func.sum(StockyardTruckLoadLine.no_of_loaded_bags))
        .join(TruckTrip, TruckTrip.id == StockyardTruckLoadLine.trip_id)
        .join(BrokerBooking, BrokerBooking.id == TruckTrip.broker_booking_id)
        .join(Brokerage, Brokerage.id == BrokerBooking.brokerage_id)
        .group_by(StockyardTruckLoadLine.stockyard_id, Brokerage.grain_id), StockyardTruckLoadLine.stockyard_id, Brokerage.grain_id)
    for sy, gr, n in (await db.execute(loaded)).all():
        out.setdefault((sy, gr), Filled()).loaded = int(n)
    return out


async def empty_ledger(db: AsyncSession, stockyard_id: int | None = None, grain_id: int | None = None) -> dict[Key, Empty]:
    out: dict[Key, Empty] = {}
    bought = select(EmptyBag.stockyard_id, EmptyBag.grain_id, func.sum(EmptyBag.no_of_empty_bags)).group_by(EmptyBag.stockyard_id, EmptyBag.grain_id)
    per_purchase = (select(StockyardPurchase.stockyard_id, StockyardPurchase.grain_id, StockyardPurchase.no_of_given_empty_bags,
                           func.coalesce(func.sum(StockyardPurchaseEntry.no_of_filled_bags), 0), func.coalesce(func.sum(StockyardPurchaseEntry.no_of_received_empty_bags), 0))
                    .outerjoin(StockyardPurchaseEntry, StockyardPurchaseEntry.stockyard_purchase_id == StockyardPurchase.id)
                    .group_by(StockyardPurchase.id))
    if stockyard_id is not None:
        bought, per_purchase = bought.where(EmptyBag.stockyard_id == stockyard_id), per_purchase.where(StockyardPurchase.stockyard_id == stockyard_id)
    if grain_id is not None:
        bought, per_purchase = bought.where(EmptyBag.grain_id == grain_id), per_purchase.where(StockyardPurchase.grain_id == grain_id)
    for sy, gr, n in (await db.execute(bought)).all():
        out.setdefault((sy, gr), Empty()).bought = int(n)
    for sy, gr, given, filled, received in (await db.execute(per_purchase)).all():
        e = out.setdefault((sy, gr), Empty())
        e.given += int(given)
        e.received += int(received)
        e.error += int(given) - int(filled) - int(received)
    return out


async def filled_balance(db: AsyncSession, stockyard_id: int, grain_id: int) -> int:
    return (await filled_ledger(db, stockyard_id, grain_id)).get((stockyard_id, grain_id), Filled()).balance


async def empty_balance(db: AsyncSession, stockyard_id: int, grain_id: int) -> int:
    return (await empty_ledger(db, stockyard_id, grain_id)).get((stockyard_id, grain_id), Empty()).balance
