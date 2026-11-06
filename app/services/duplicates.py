"""A farmer's entry may exist in purchase_individuals, purchase_group_farmers_entries (a purchase_group) and stockyard_purchase_entries,
but an exact copy of one entry may not exist twice, in one table or across any two of them.

Two entries are exact copies when farmer, date, grain, rate per 20 kg, filled bags and extra kilos are all the same."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PurchaseFarmerEntry, PurchaseGroup, PurchaseIndividual, StockyardPurchase, StockyardPurchaseEntry

DUPLICATE_MSG = lambda where: (  # noqa: E731
    f"The same entry (farmer, date, grain, rate, bags and kilos) already exists as {where}",
    f"આ જ નોંધ (ખેડૂત, તારીખ, અનાજ, ભાવ, બેગ અને કિલો) પહેલેથી {where} તરીકે છે",
)


async def find_duplicate(db: AsyncSession, farmer_id: int, on_date: date, grain_id: int, rate: int, filled_bags: int, extra_kilos: int,
                         own: tuple[str, int] | None = None) -> str | None:
    """Where an exact copy already lives ('purchase individual #3', ...), or None. `own` = (table, id) of the row being edited."""
    same = dict(bags=filled_bags, kilos=extra_kilos)
    found = await db.scalar(select(PurchaseIndividual.id).where(
        PurchaseIndividual.farmer_id == farmer_id, PurchaseIndividual.purchase_individual_date == on_date, PurchaseIndividual.grain_id == grain_id,
        PurchaseIndividual.grain_rate_per_20kg == rate, PurchaseIndividual.no_of_filled_bags == same["bags"], PurchaseIndividual.extra_kilos == same["kilos"],
        PurchaseIndividual.id != (own[1] if own and own[0] == "purchase_individuals" else 0)).limit(1))
    if found:
        return f"purchase individual #{found}"
    found = await db.scalar(select(PurchaseFarmerEntry.id).join(PurchaseGroup, PurchaseGroup.id == PurchaseFarmerEntry.purchase_group_id).where(
        PurchaseFarmerEntry.farmer_id == farmer_id, PurchaseFarmerEntry.purchase_entry_date == on_date, PurchaseGroup.grain_id == grain_id,
        PurchaseGroup.grain_rate_per_20kg == rate, PurchaseFarmerEntry.no_of_filled_bags == same["bags"], PurchaseFarmerEntry.extra_kilos == same["kilos"],
        PurchaseFarmerEntry.id != (own[1] if own and own[0] == "purchase_group_farmers_entries" else 0)).limit(1))
    if found:
        return f"purchase group entry #{found}"
    found = await db.scalar(select(StockyardPurchaseEntry.id).join(StockyardPurchase, StockyardPurchase.id == StockyardPurchaseEntry.stockyard_purchase_id).where(
        StockyardPurchase.farmer_id == farmer_id, StockyardPurchaseEntry.stockyard_purchase_entry_date == on_date, StockyardPurchase.grain_id == grain_id,
        StockyardPurchase.grain_rate_per_20kg == rate, StockyardPurchaseEntry.no_of_filled_bags == same["bags"], StockyardPurchaseEntry.extra_kilos == same["kilos"],
        StockyardPurchaseEntry.id != (own[1] if own and own[0] == "stockyard_purchase_entries" else 0)).limit(1))
    if found:
        return f"stockyard purchase entry #{found}"
    return None
