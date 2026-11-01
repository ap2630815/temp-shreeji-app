"""Stockyard bag ledgers, per stockyard and grain. Nothing is stored: every figure is worked out from the records.

Filled bags   in  = stockyard purchase entries (no_of_filled_bags) + farmer_stockyard_transfers (bags brought from a farmer's place)
              out = stockyard_truck_load_lines (bags loaded on a truck)
Empty bags    in  = stockyard_empty_bag_movements 'received'
              out = stockyard_empty_bag_movements 'given_to_farmer'
                    + bags used by stockyard purchase entries: when one entry's filled bags exceed the empty bags given on its
                      purchase (stockyard_purchases.no_of_empty_bags), the excess is taken from the stockyard's empty bags.
                      Each entry is compared on its own; only stockyard purchase entries use the pool this way."""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    BrokerBooking, Brokerage, FarmerStockyardTransfer, TruckTrip, PurchaseFarmerEntry, PurchaseGroup, PurchaseIndividual, StockyardEmptyBagMovement, StockyardTruckLoadLine,
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
    received: int = 0
    given: int = 0
    used: int = 0  # taken for stockyard purchase entries

    @property
    def balance(self) -> int:
        return self.received - self.given - self.used


def empties_needed(filled_bags: int, empty_bags_given: int) -> int:
    """Empty bags one stockyard purchase entry takes from the stockyard: its filled bags beyond the empty bags given on its purchase."""
    return max(0, filled_bags - empty_bags_given)


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
        select(FarmerStockyardTransfer.stockyard_id, PurchaseGroup.grain_id, func.sum(FarmerStockyardTransfer.no_of_bags))
        .join(PurchaseFarmerEntry, PurchaseFarmerEntry.id == FarmerStockyardTransfer.purchase_farmer_entry_id)
        .join(PurchaseGroup, PurchaseGroup.id == PurchaseFarmerEntry.purchase_group_id)
        .group_by(FarmerStockyardTransfer.stockyard_id, PurchaseGroup.grain_id), FarmerStockyardTransfer.stockyard_id, PurchaseGroup.grain_id)
    from_individual = keep(
        select(FarmerStockyardTransfer.stockyard_id, PurchaseIndividual.grain_id, func.sum(FarmerStockyardTransfer.no_of_bags))
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
    moves = select(StockyardEmptyBagMovement.stockyard_id, StockyardEmptyBagMovement.grain_id, StockyardEmptyBagMovement.movement_type,
                   func.sum(StockyardEmptyBagMovement.no_of_bags)).group_by(
        StockyardEmptyBagMovement.stockyard_id, StockyardEmptyBagMovement.grain_id, StockyardEmptyBagMovement.movement_type)
    used = (select(StockyardPurchase.stockyard_id, StockyardPurchase.grain_id, StockyardPurchase.no_of_empty_bags, StockyardPurchaseEntry.no_of_filled_bags)
            .join(StockyardPurchase, StockyardPurchase.id == StockyardPurchaseEntry.stockyard_purchase_id))
    if stockyard_id is not None:
        moves, used = moves.where(StockyardEmptyBagMovement.stockyard_id == stockyard_id), used.where(StockyardPurchase.stockyard_id == stockyard_id)
    if grain_id is not None:
        moves, used = moves.where(StockyardEmptyBagMovement.grain_id == grain_id), used.where(StockyardPurchase.grain_id == grain_id)
    for sy, gr, kind, n in (await db.execute(moves)).all():
        e = out.setdefault((sy, gr), Empty())
        if kind == "received":
            e.received = int(n)
        else:
            e.given = int(n)
    for sy, gr, given_on_purchase, filled in (await db.execute(used)).all():
        out.setdefault((sy, gr), Empty()).used += empties_needed(int(filled), given_on_purchase)
    return out


async def filled_balance(db: AsyncSession, stockyard_id: int, grain_id: int) -> int:
    return (await filled_ledger(db, stockyard_id, grain_id)).get((stockyard_id, grain_id), Filled()).balance


async def empty_balance(db: AsyncSession, stockyard_id: int, grain_id: int) -> int:
    return (await empty_ledger(db, stockyard_id, grain_id)).get((stockyard_id, grain_id), Empty()).balance
