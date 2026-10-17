"""The farmers listed on a purchase_group (one deal with the few farmers who gathered in a village).

Only ledger entries (purchase_farmers_entries) hang off a listed farmer at this stage, so taking a farmer off the list
simply deletes his entries in that purchase. If an entry has already been used by a later step (loaded on a truck or paid),
the farmer cannot be removed: that is reported on the form, nothing is deleted."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Farmer, PaymentAllocation, PurchaseFarmerEntry, PurchaseGroup, PurchaseGroupFarmer, TruckLoadLine, User
from app.services import audit

Pair = tuple[str, str]


async def other_deals(db: AsyncSession, farmer_ids: list[int], grain_id: int, business_year: str, exclude_info_id: int | None = None) -> dict[int, list[PurchaseGroup]]:
    """For each farmer, the other purchase_group of the same grain and business year he is already listed on."""
    if not farmer_ids:
        return {}
    stmt = (
        select(PurchaseGroupFarmer.farmer_id, PurchaseGroup)
        .join(PurchaseGroup, PurchaseGroup.id == PurchaseGroupFarmer.purchase_group_id)
        .where(PurchaseGroupFarmer.farmer_id.in_(farmer_ids), PurchaseGroup.grain_id == grain_id, PurchaseGroup.business_year == business_year)
        .order_by(PurchaseGroup.purchase_group_date, PurchaseGroup.id)
    )
    if exclude_info_id is not None:
        stmt = stmt.where(PurchaseGroup.id != exclude_info_id)
    out: dict[int, list[PurchaseGroup]] = {}
    for fid, info in (await db.execute(stmt)).unique().all():
        out.setdefault(fid, []).append(info)
    return out


async def listed_farmer_ids(db: AsyncSession, purchase_group_id: int) -> list[int]:
    return list((await db.scalars(select(PurchaseGroupFarmer.farmer_id).where(PurchaseGroupFarmer.purchase_group_id == purchase_group_id).order_by(PurchaseGroupFarmer.id))).all())


async def entries_of(db: AsyncSession, purchase_group_id: int, farmer_ids: list[int]) -> list[PurchaseFarmerEntry]:
    if not farmer_ids:
        return []
    return list((await db.scalars(
        select(PurchaseFarmerEntry).where(PurchaseFarmerEntry.purchase_group_id == purchase_group_id, PurchaseFarmerEntry.farmer_id.in_(farmer_ids))
        .order_by(PurchaseFarmerEntry.id)
    )).unique().all())


async def in_use(db: AsyncSession, entries: list[PurchaseFarmerEntry]) -> list[Farmer]:
    """Farmers (of these entries) whose entry is already loaded on a truck or has a payment against it."""
    if not entries:
        return []
    ids = [e.id for e in entries]
    used = set((await db.scalars(select(TruckLoadLine.purchase_farmer_entry_id).where(TruckLoadLine.purchase_farmer_entry_id.in_(ids)))).all())
    used |= set((await db.scalars(select(PaymentAllocation.payable_id).where(PaymentAllocation.payable_type == "farmer", PaymentAllocation.payable_id.in_(ids)))).all())
    farmers = {e.farmer_id: e.farmer for e in entries if e.id in used}
    return sorted(farmers.values(), key=lambda f: f.farmer_name)


async def remove_farmers(db: AsyncSession, user: User, purchase_group_id: int, farmer_ids: list[int], entries: list[PurchaseFarmerEntry]) -> None:
    """Delete the farmers' entries in this purchase and take them off the list. Caller commits."""
    for e in entries:
        audit.log(db, user, "delete", "purchase_farmers_entries", e.id, dict(farmer_id=e.farmer_id, no_of_filled_bags=e.no_of_filled_bags, payable_amount=e.payable_amount,
                                                                              reason="farmer removed from purchase_group"))
        await db.delete(e)
    await db.flush()
    for row in (await db.scalars(select(PurchaseGroupFarmer).where(PurchaseGroupFarmer.purchase_group_id == purchase_group_id, PurchaseGroupFarmer.farmer_id.in_(farmer_ids)))).unique().all():
        audit.log(db, user, "delete", "purchase_group_farmers", row.id, dict(purchase_group_id=purchase_group_id, farmer_id=row.farmer_id))
        await db.delete(row)
    await db.flush()
