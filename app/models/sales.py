"""Sales side: truck trips, load lines (stock leaving villages), bilty (weights + receivable), industry receipts,
plus the other costs (labour work, bag supplies).

Same rules as the village flow: whole rupees, integer kg, and paid/due/status derived from allocations."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import BigInteger, CheckConstraint, Date, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.masters import Broker, Farmer, Grain, Industry, LabourGroup, BagSupplier, Transporter, Truck
from app.models.village import Commencing


def _ceil_div(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


def freight_amount(weight_kg: int | None, bags: int, rent_per_ton: int, rent_per_bag: int) -> int:
    """max((weight / 1000) * rent_per_ton, bags * rent_per_bag), rounded up to whole rupees."""
    by_weight = _ceil_div(weight_kg * rent_per_ton, 1000) if weight_kg else 0
    return max(by_weight, bags * rent_per_bag)


class TruckTrip(TimestampMixin, Base):
    """One truck carries one grain on one trip, loaded from one or more commencings, unloaded at one industry."""

    __tablename__ = "truck_trips"
    __table_args__ = (
        CheckConstraint("rent_per_ton >= 0 AND rent_per_bag >= 0", name="ck_trips_rent_nonneg"),
        CheckConstraint("advance_amount >= 0 AND other_deduction >= 0", name="ck_trips_amounts_nonneg"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_year: Mapped[str] = mapped_column(String(7), index=True)
    trip_date: Mapped[date] = mapped_column(Date)
    truck_id: Mapped[int] = mapped_column(ForeignKey("trucks.id"))
    transport_id: Mapped[int] = mapped_column(ForeignKey("transporters.id"))
    labour_group_id: Mapped[int] = mapped_column(ForeignKey("labour_groups.id"))
    industry_id: Mapped[int] = mapped_column(ForeignKey("industries.id"))
    grain_id: Mapped[int] = mapped_column(ForeignKey("grains.id"))
    rent_per_ton: Mapped[int] = mapped_column(Integer, default=0)
    rent_per_bag: Mapped[int] = mapped_column(Integer, default=0)
    advance_amount: Mapped[int] = mapped_column(BigInteger, default=0)  # given to the driver at loading
    other_deduction: Mapped[int] = mapped_column(BigInteger, default=0)
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    truck: Mapped[Truck] = relationship(lazy="joined")
    transport: Mapped[Transporter] = relationship(lazy="joined")
    labour_group: Mapped[LabourGroup] = relationship(lazy="joined")
    industry: Mapped[Industry] = relationship(lazy="joined")
    grain: Mapped[Grain] = relationship(lazy="joined")
    bilty: Mapped["Bilty | None"] = relationship(back_populates="trip", uselist=False, lazy="joined")
    load_lines: Mapped[list["TruckLoadLine"]] = relationship(lazy="selectin", order_by="TruckLoadLine.id")

    @property
    def bags(self) -> int:
        return sum(line.bags for line in self.load_lines)

    @property
    def freight_weight_kg(self) -> int | None:
        """Freight is charged on the industry's weight; until unloaded the merchant weight is a provisional stand-in."""
        if self.bilty is None:
            return None
        return self.bilty.industry_net_weight if self.bilty.industry_net_weight is not None else self.bilty.merchant_net_weight

    @property
    def freight_is_provisional(self) -> bool:
        return self.bilty is None or self.bilty.industry_net_weight is None

    @property
    def freight(self) -> int:
        return freight_amount(self.freight_weight_kg, self.bags, self.rent_per_ton, self.rent_per_bag)

    @property
    def freight_by_weight(self) -> int:
        return _ceil_div(self.freight_weight_kg * self.rent_per_ton, 1000) if self.freight_weight_kg else 0

    @property
    def freight_by_bags(self) -> int:
        return self.bags * self.rent_per_bag

    @property
    def final_payment(self) -> int:
        """What is still owed to the transporter after the advance already handed over and other deductions."""
        return max(self.freight - self.advance_amount - self.other_deduction, 0)


class TruckLoadLine(Base):
    __tablename__ = "truck_load_lines"
    __table_args__ = (CheckConstraint("bags > 0", name="ck_load_lines_bags"), Index("ix_load_lines_commencing", "commencing_id"))

    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("truck_trips.id"), index=True)
    commencing_id: Mapped[int] = mapped_column(ForeignKey("commencings.id"))
    bags: Mapped[int] = mapped_column(Integer)

    commencing: Mapped[Commencing] = relationship(lazy="joined")


class Bilty(TimestampMixin, Base):
    """The consignment note for a trip: weights at both ends, the sale rate, the broker, and thereby the receivable."""

    __tablename__ = "bilties"
    __table_args__ = (
        UniqueConstraint("business_year", "bill_number", name="uq_bilties_year_bill"),
        CheckConstraint("bill_number > 0", name="ck_bilties_bill_number"),
        CheckConstraint("grain_rate > 0 AND rate_unit_kg > 0", name="ck_bilties_rate"),
        CheckConstraint("grain_rate - rate_change >= 0", name="ck_bilties_rate_change"),
        CheckConstraint("brokerage_amount >= 0", name="ck_bilties_brokerage"),
        CheckConstraint("merchant_total_weight > merchant_tare_weight AND merchant_tare_weight >= 0", name="ck_bilties_merchant_weights"),
        CheckConstraint(
            "(industry_total_weight IS NULL AND industry_tare_weight IS NULL) OR "
            "(industry_total_weight > industry_tare_weight AND industry_tare_weight >= 0)",
            name="ck_bilties_industry_weights",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("truck_trips.id"), unique=True)
    business_year: Mapped[str] = mapped_column(String(7), index=True)
    bilty_date: Mapped[date] = mapped_column(Date)
    bill_number: Mapped[int] = mapped_column(Integer)
    broker_id: Mapped[int] = mapped_column(ForeignKey("brokers.id"))
    grain_rate: Mapped[int] = mapped_column(Integer)  # rupees per rate_unit_kg
    rate_unit_kg: Mapped[int] = mapped_column(Integer, default=20)
    rate_change: Mapped[int] = mapped_column(Integer, default=0)  # agreed reduction (+) or increase (-) after delivery
    brokerage_amount: Mapped[int] = mapped_column(Integer, default=0)  # snapshot of broker.brokerage_per_truck
    merchant_total_weight: Mapped[int] = mapped_column(Integer)  # kg, loaded truck at our weighbridge
    merchant_tare_weight: Mapped[int] = mapped_column(Integer)
    industry_total_weight: Mapped[int | None] = mapped_column(Integer)  # kg, as weighed at the industry
    industry_tare_weight: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)  # mismatch, 120 bags unloaded, ...
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    trip: Mapped[TruckTrip] = relationship(back_populates="bilty", lazy="joined")
    broker: Mapped[Broker] = relationship(lazy="joined")

    # ---- weights
    @property
    def merchant_net_weight(self) -> int:
        return self.merchant_total_weight - self.merchant_tare_weight

    @property
    def industry_net_weight(self) -> int | None:
        if self.industry_total_weight is None:
            return None
        return self.industry_total_weight - self.industry_tare_weight

    def _diff(self, merchant: int, industry: int | None) -> int | None:
        return None if industry is None else merchant - industry

    @property
    def difference_total_weight(self) -> int | None:
        return self._diff(self.merchant_total_weight, self.industry_total_weight)

    @property
    def difference_tare_weight(self) -> int | None:
        return self._diff(self.merchant_tare_weight, self.industry_tare_weight)

    @property
    def difference_net_weight(self) -> int | None:
        return self._diff(self.merchant_net_weight, self.industry_net_weight)

    @property
    def percentage_difference(self) -> Decimal | None:
        """(difference in grain weight / merchant grain weight) * 100; positive = the industry weighed less."""
        diff = self.difference_net_weight
        if diff is None:
            return None
        return (Decimal(diff) * 100 / Decimal(self.merchant_net_weight)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # ---- money
    @property
    def effective_rate(self) -> int:
        return self.grain_rate - self.rate_change

    @property
    def receivable_amount(self) -> int | None:
        """(industry grain weight / rate unit) * (rate - rate change), rounded up. None until the industry weight is in."""
        if self.industry_net_weight is None:
            return None
        return _ceil_div(self.industry_net_weight * self.effective_rate, self.rate_unit_kg)

    @property
    def estimated_amount(self) -> int:
        """What we expected to bill, from our own weight at the original rate."""
        return _ceil_div(self.merchant_net_weight * self.grain_rate, self.rate_unit_kg)

    @property
    def error_receivable_amount(self) -> int | None:
        return None if self.receivable_amount is None else self.receivable_amount - self.estimated_amount


class Receipt(TimestampMixin, Base):
    """Money received from an industry; allocations say which bilties it settled."""

    __tablename__ = "receipts"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_receipts_amount"),
        CheckConstraint("method IN ('cash', 'cheque', 'upi', 'bank')", name="ck_receipts_method"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    industry_id: Mapped[int] = mapped_column(ForeignKey("industries.id"), index=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    receipt_date: Mapped[date] = mapped_column(Date)
    business_year: Mapped[str] = mapped_column(String(7), index=True)
    method: Mapped[str] = mapped_column(String(10))
    reference_no: Mapped[str | None] = mapped_column(String(60))
    payer_name: Mapped[str | None] = mapped_column(String(200))
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    industry: Mapped[Industry] = relationship(lazy="joined")
    allocations: Mapped[list["ReceiptAllocation"]] = relationship(lazy="selectin", order_by="ReceiptAllocation.id")


class ReceiptAllocation(Base):
    __tablename__ = "receipt_allocations"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_receipt_alloc_amount"), Index("ix_receipt_alloc_bilty", "bilty_id"))

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipts.id"))
    bilty_id: Mapped[int] = mapped_column(ForeignKey("bilties.id"))
    amount: Mapped[int] = mapped_column(BigInteger)


class LabourWork(TimestampMixin, Base):
    """A labour group's day: what they earned, what they borrowed (deducted), and petrol/meal we covered (not deducted)."""

    __tablename__ = "labour_work"
    __table_args__ = (
        CheckConstraint("payable_amount >= 0 AND borrowing_amount >= 0 AND petrol >= 0 AND meal >= 0", name="ck_labour_nonneg"),
        CheckConstraint("borrowing_amount <= payable_amount", name="ck_labour_borrowing_le_payable"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    labour_group_id: Mapped[int] = mapped_column(ForeignKey("labour_groups.id"), index=True)
    work_date: Mapped[date] = mapped_column(Date)
    business_year: Mapped[str] = mapped_column(String(7), index=True)
    payable_amount: Mapped[int] = mapped_column(BigInteger, default=0)
    borrowing_amount: Mapped[int] = mapped_column(BigInteger, default=0)
    petrol: Mapped[int] = mapped_column(BigInteger, default=0)
    meal: Mapped[int] = mapped_column(BigInteger, default=0)
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    labour_group: Mapped[LabourGroup] = relationship(lazy="joined")

    @property
    def net_payable(self) -> int:
        return self.payable_amount - self.borrowing_amount


class BagSupply(TimestampMixin, Base):
    """Bags a supplier delivered to a farmer's place. A business cost, never deducted from the farmer."""

    __tablename__ = "bag_supplies"
    __table_args__ = (CheckConstraint("rate > 0 AND units > 0", name="ck_bag_supplies_positive"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("bag_suppliers.id"), index=True)
    farmer_id: Mapped[int] = mapped_column(ForeignKey("farmers.id"), index=True)
    supply_date: Mapped[date] = mapped_column(Date)
    business_year: Mapped[str] = mapped_column(String(7), index=True)
    rate: Mapped[int] = mapped_column(Integer)  # rupees per bag
    units: Mapped[int] = mapped_column(Integer)
    payable_amount: Mapped[int] = mapped_column(BigInteger)  # rate * units
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    supplier: Mapped[BagSupplier] = relationship(lazy="joined")
    farmer: Mapped[Farmer] = relationship(lazy="joined")
