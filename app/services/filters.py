"""The toolbar filters (village / grain) as query conditions, so every list that has a village or grain behind it narrows the same way."""

from sqlalchemy import select

from app.models import BrokerBooking, Brokerage, PurchaseFarmerEntry, PurchaseGroup, PurchaseIndividual, FarmersTruckLoadLine, TruckTrip


def trip_conditions(grain_id: int = 0, village_id: int = 0) -> list:
    """Conditions on TruckTrip: the grain of its booking, and the village its loaded bags were bought in."""
    conds = []
    if grain_id:
        conds.append(TruckTrip.broker_booking_id.in_(
            select(BrokerBooking.id).join(Brokerage, Brokerage.id == BrokerBooking.brokerage_id).where(Brokerage.grain_id == grain_id)))
    if village_id:
        from_group = (
            select(FarmersTruckLoadLine.trip_id)
            .join(PurchaseFarmerEntry, PurchaseFarmerEntry.id == FarmersTruckLoadLine.purchase_farmer_entry_id)
            .join(PurchaseGroup, PurchaseGroup.id == PurchaseFarmerEntry.purchase_group_id)
            .where(PurchaseGroup.village_id == village_id))
        from_individual = (
            select(FarmersTruckLoadLine.trip_id)
            .join(PurchaseIndividual, PurchaseIndividual.id == FarmersTruckLoadLine.purchase_individual_id)
            .where(PurchaseIndividual.village_id == village_id))
        conds.append(TruckTrip.id.in_(from_group) | TruckTrip.id.in_(from_individual))
    return conds
