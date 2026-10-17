"""The toolbar filters (village / grain) as query conditions, so every list that has a village or grain behind it narrows the same way."""

from sqlalchemy import select

from app.models import BrokerBooking, Brokerage, PurchaseFarmerEntry, PurchaseGroup, TruckLoadLine, TruckTrip


def trip_conditions(grain_id: int = 0, village_id: int = 0) -> list:
    """Conditions on TruckTrip: the grain of its booking, and the village its loaded bags were bought in."""
    conds = []
    if grain_id:
        conds.append(TruckTrip.broker_booking_id.in_(
            select(BrokerBooking.id).join(Brokerage, Brokerage.id == BrokerBooking.brokerage_id).where(Brokerage.grain_id == grain_id)))
    if village_id:
        conds.append(TruckTrip.id.in_(
            select(TruckLoadLine.trip_id)
            .join(PurchaseFarmerEntry, PurchaseFarmerEntry.id == TruckLoadLine.purchase_farmer_entry_id)
            .join(PurchaseGroup, PurchaseGroup.id == PurchaseFarmerEntry.purchase_group_id)
            .where(PurchaseGroup.village_id == village_id)))
    return conds
