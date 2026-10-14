"""Form tables (file4-transactional.txt): records entered through the data-entry forms.

Whole rupees (BigInteger) and integer kg. Every dated record carries a business_year (1 Oct - 30 Sep, e.g. '2025-26'),
set by the application from the record's own date (file9-database.txt, rule 5)."""

from datetime import date

from sqlalchemy import BigInteger, CheckConstraint, Date, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.masters import Brokerage, Farmer, Grain, Industry, LabourGroup, BagSupplier, Transporter, Truck, Village
from app.services import money

BUSINESS_YEAR = r"^[0-9]{4}-[0-9]{2}$"


def _year_check(table: str) -> CheckConstraint:
    return CheckConstraint(f"business_year ~ '{BUSINESS_YEAR}'", name=f"ck_{table}_business_year_format")


def _year_index(table: str) -> Index:
    return Index(f"ix_{table}_business_year", "business_year")


class PurchaseInfo(TimestampMixin, Base):
    """A village deal: the whole village sells one grain at one rate on agreed terms."""

    __tablename__ = "purchase_info"
    __table_args__ = (
        _year_check("purchase_info"),
        _year_index("purchase_info"),
        CheckConstraint("grain_rate_per_20kg > 0", name="ck_purchase_info_rate_positive"),
        CheckConstraint("pay_after_no_of_days >= 0", name="ck_purchase_info_pay_after"),
        Index("ix_purchase_info_village_id", "village_id"),
        Index("ix_purchase_info_grain_id", "grain_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_info_date: Mapped[date] = mapped_column(Date)
    village_id: Mapped[int] = mapped_column(ForeignKey("villages.id"))
    grain_id: Mapped[int] = mapped_column(ForeignKey("grains.id"))
    grain_rate_per_20kg: Mapped[int] = mapped_column(Integer)
    pay_after_no_of_days: Mapped[int] = mapped_column(Integer)
    purchase_info_terms: Mapped[str | None] = mapped_column(Text)
    business_year: Mapped[str] = mapped_column(String(7))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    village: Mapped[Village] = relationship(lazy="joined")
    grain: Mapped[Grain] = relationship(lazy="joined")


class PurchaseFarmerEntry(TimestampMixin, Base):
    """One farmer's weighed grain inside a purchase_info."""

    __tablename__ = "purchase_farmer_entries"
    __table_args__ = (
        _year_check("purchase_farmer_entries"),
        _year_index("purchase_farmer_entries"),
        CheckConstraint("extra_kilos >= 0", name="ck_purchase_farmer_entries_extra_kilos"),
        CheckConstraint("no_of_filled_bags >= 0", name="ck_purchase_farmer_entries_no_of_filled_bags"),
        CheckConstraint("payable_amount >= 0", name="ck_purchase_farmer_entries_payable_amount"),
        CheckConstraint("borrowed_amount >= 0", name="ck_purchase_farmer_entries_borrowed_amount"),
        CheckConstraint("borrowed_amount <= payable_amount", name="ck_purchase_farmer_entries_borrowed_amount_le_payable_amount"),
        CheckConstraint(
            "expected_raw_weight_per_bag IS NULL OR expected_raw_weight_per_bag >= 0",
            name="ck_purchase_farmer_entries_expected_raw_weight_per_bag",
        ),
        CheckConstraint("no_of_handful_bags >= 0", name="ck_purchase_farmer_entries_no_of_handful_bags"),
        CheckConstraint("total_available_bags >= 0", name="ck_purchase_farmer_entries_total_available_bags"),
        Index("ix_purchase_farmer_entries_purchase_info_id", "purchase_info_id"),
        Index("ix_purchase_farmer_entries_farmer_id", "farmer_id"),
        Index("ix_purchase_farmer_entries_labour_group_id", "labour_group_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_entry_date: Mapped[date] = mapped_column(Date)
    purchase_info_id: Mapped[int] = mapped_column(ForeignKey("purchase_info.id"))
    farmer_id: Mapped[int] = mapped_column(ForeignKey("farmers.id"))
    labour_group_id: Mapped[int] = mapped_column(ForeignKey("labour_groups.id"))
    no_of_filled_bags: Mapped[int] = mapped_column(Integer)
    extra_kilos: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    payable_amount: Mapped[int] = mapped_column(BigInteger)
    borrowed_amount: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    due_date: Mapped[date] = mapped_column(Date)
    expected_raw_weight_per_bag: Mapped[int | None] = mapped_column(Integer)
    grain_quality_code: Mapped[str | None] = mapped_column(Text)
    grain_store_at: Mapped[str | None] = mapped_column(Text)
    no_of_handful_bags: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_available_bags: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    business_year: Mapped[str] = mapped_column(String(7))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    purchase_info: Mapped[PurchaseInfo] = relationship(lazy="joined")
    farmer: Mapped[Farmer] = relationship(lazy="joined")
    labour_group: Mapped[LabourGroup] = relationship(lazy="joined")

    @property
    def net_payable(self) -> int:
        """payable_amount - borrowed_amount: what the farmer is still to be paid."""
        return self.payable_amount - self.borrowed_amount

    @property
    def total_kg(self) -> int:
        return self.no_of_filled_bags * self.purchase_info.grain.net_bag_weight + self.extra_kilos


class BrokerBooking(TimestampMixin, Base):
    """An order booked through a broker: industry, sale rate per booking weight, truck size, deduction."""

    __tablename__ = "broker_bookings"
    __table_args__ = (
        _year_check("broker_bookings"),
        _year_index("broker_bookings"),
        Index("ix_broker_bookings_brokerage_id", "brokerage_id"),
        Index("ix_broker_bookings_industry_id", "industry_id"),
        CheckConstraint("truck_size IN (10, 15, 20, 25, 30, 35)", name="ck_broker_bookings_truck_size"),
        CheckConstraint(
            "percentage_deduction IS NULL OR percentage_deduction BETWEEN 0 AND 5",
            name="ck_broker_bookings_percentage_deduction",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_date: Mapped[date] = mapped_column(Date)
    brokerage_id: Mapped[int] = mapped_column(ForeignKey("brokerages.id"))
    industry_id: Mapped[int] = mapped_column(ForeignKey("industries.id"))
    grain_rate_per_booking_weight: Mapped[int] = mapped_column(Integer)
    truck_size: Mapped[int] = mapped_column(Integer)
    percentage_deduction: Mapped[float | None] = mapped_column(Float)
    business_year: Mapped[str] = mapped_column(String(7))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    brokerage: Mapped[Brokerage] = relationship(lazy="joined")
    industry: Mapped[Industry] = relationship(lazy="joined")

    @property
    def grain(self) -> Grain:
        return self.brokerage.grain


class TruckTrip(TimestampMixin, Base):
    __tablename__ = "truck_trips"
    __table_args__ = (
        _year_check("truck_trips"),
        _year_index("truck_trips"),
        CheckConstraint("advance_amount >= 0 AND other_payable >= 0 AND other_deduction >= 0", name="ck_truck_trips_amount_nonneg"),
        CheckConstraint(
            "(rent_per_ton > 0 AND rent_per_bag = 0) OR (rent_per_ton = 0 AND rent_per_bag > 0)",
            name="ck_truck_trips_rent_nonneg",
        ),
        Index("ix_truck_trips_broker_booking_id", "broker_booking_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    trip_date: Mapped[date] = mapped_column(Date)
    broker_booking_id: Mapped[int] = mapped_column(ForeignKey("broker_bookings.id"))
    truck_id: Mapped[int] = mapped_column(ForeignKey("trucks.id"))
    transporter_id: Mapped[int] = mapped_column(ForeignKey("transporters.id"))
    labour_group_id: Mapped[int] = mapped_column(ForeignKey("labour_groups.id"))
    rent_per_ton: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rent_per_bag: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    advance_amount: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    other_payable: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    other_deduction: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    business_year: Mapped[str] = mapped_column(String(7))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    broker_booking: Mapped[BrokerBooking] = relationship(lazy="joined")
    truck: Mapped[Truck] = relationship(lazy="joined")
    transporter: Mapped[Transporter] = relationship(lazy="joined")
    labour_group: Mapped[LabourGroup] = relationship(lazy="joined")
    bilty: Mapped["Bilty | None"] = relationship(back_populates="trip", uselist=False, lazy="joined")
    load_lines: Mapped[list["TruckLoadLine"]] = relationship(lazy="selectin", order_by="TruckLoadLine.id")

    @property
    def industry(self) -> Industry:
        return self.broker_booking.industry

    @property
    def grain(self) -> Grain:
        return self.broker_booking.brokerage.grain

    @property
    def bags(self) -> int:
        """total_bags_in_truck: the sum of the loaded bags over the trip's load lines."""
        return sum(line.no_of_loaded_bags for line in self.load_lines)

    @property
    def freight_weight_kg(self) -> int | None:
        """Freight is charged on the industry's weight; until unloaded our own weight is a provisional stand-in."""
        if self.bilty is None:
            return None
        b = self.bilty
        return b.industry_net_weight if b.industry_net_weight is not None else b.merchant_net_weight

    @property
    def freight_is_provisional(self) -> bool:
        return self.bilty is None or self.bilty.industry_net_weight is None

    @property
    def freight_by_weight(self) -> int:
        return money.trip_freight_by_weight(self.freight_weight_kg, self.rent_per_ton)

    @property
    def freight_by_bags(self) -> int:
        return money.trip_freight_by_bags(self.bags, self.rent_per_bag)

    @property
    def trip_total(self) -> int:
        return self.freight_by_weight + self.freight_by_bags

    @property
    def total_amount(self) -> int:
        """truck_trip_total_amount = trip_total - advance_amount + other_payable - other_deduction."""
        return money.truck_trip_total_amount(self.trip_total, self.advance_amount, self.other_payable, self.other_deduction)


class TruckLoadLine(Base):
    """Bags of one farmer entry loaded on one trip (no date of its own: it belongs to its trip's year)."""

    __tablename__ = "truck_load_lines"
    __table_args__ = (
        CheckConstraint("no_of_loaded_bags > 0", name="ck_truck_load_lines_no_of_loaded_bags"),
        CheckConstraint("total_remaining_bags >= 0", name="ck_truck_load_lines_total_remaining_bags"),
        Index("ix_truck_load_lines_purchase_farmer_entry_id", "purchase_farmer_entry_id"),
        UniqueConstraint("trip_id", "purchase_farmer_entry_id", name="uq_truck_load_lines_trip_entry"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("truck_trips.id"))
    purchase_farmer_entry_id: Mapped[int] = mapped_column(ForeignKey("purchase_farmer_entries.id"))
    no_of_loaded_bags: Mapped[int] = mapped_column(Integer)
    total_remaining_bags: Mapped[int] = mapped_column(Integer)

    entry: Mapped[PurchaseFarmerEntry] = relationship(lazy="joined")


class Bilty(TimestampMixin, Base):
    """The consignment note for a trip: weights at both ends."""

    __tablename__ = "bilties"
    __table_args__ = (
        _year_check("bilties"),
        _year_index("bilties"),
        CheckConstraint("merchant_total_weight > merchant_tare_weight AND merchant_tare_weight >= 0", name="ck_bilties_merchant_weights"),
        CheckConstraint(
            "(industry_total_weight IS NULL AND industry_tare_weight IS NULL) OR "
            "(industry_total_weight > industry_tare_weight AND industry_tare_weight >= 0)",
            name="ck_bilties_industry_weights",
        ),
        CheckConstraint("bill_number > 0", name="ck_bilties_bill_number"),
        UniqueConstraint("business_year", "bill_number", name="uq_bilties_year_bill"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    bilty_date: Mapped[date] = mapped_column(Date)
    bill_number: Mapped[int] = mapped_column(Integer)
    truck_trip_id: Mapped[int] = mapped_column(ForeignKey("truck_trips.id"), unique=True)
    total_bags_in_truck: Mapped[int] = mapped_column(Integer)
    any_rate_change: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    merchant_total_weight: Mapped[int] = mapped_column(Integer)
    merchant_tare_weight: Mapped[int] = mapped_column(Integer)
    industry_total_weight: Mapped[int | None] = mapped_column(Integer)
    industry_tare_weight: Mapped[int | None] = mapped_column(Integer)
    business_year: Mapped[str] = mapped_column(String(7))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    trip: Mapped[TruckTrip] = relationship(back_populates="bilty", lazy="joined")

    # ---- weights (kg)
    @property
    def merchant_net_weight(self) -> int:
        return self.merchant_total_weight - self.merchant_tare_weight

    @property
    def industry_net_weight(self) -> int | None:
        if self.industry_total_weight is None:
            return None
        return self.industry_total_weight - self.industry_tare_weight

    @property
    def expected_total_loaded_weight(self) -> int | None:
        return money.expected_total_loaded_weight(
            [(line.no_of_loaded_bags, line.entry.expected_raw_weight_per_bag) for line in self.trip.load_lines]
        )

    @property
    def difference_in_loading_weight(self) -> int | None:
        """(merchant_total_weight - merchant_tare_weight) - expected_total_loaded_weight."""
        expected = self.expected_total_loaded_weight
        return None if expected is None else self.merchant_net_weight - expected

    @property
    def average_per_bag_difference(self) -> Decimal | None:
        diff = self.difference_in_loading_weight
        if diff is None or not self.total_bags_in_truck:
            return None
        return (Decimal(diff) / self.total_bags_in_truck).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def difference_in_delivering_weight(self) -> int | None:
        """(industry_total - industry_tare) - (merchant_total - merchant_tare); negative = industry weighed less."""
        n = self.industry_net_weight
        return None if n is None else n - self.merchant_net_weight

    @property
    def total_weight_difference(self) -> int | None:
        return None if self.industry_total_weight is None else self.industry_total_weight - self.merchant_total_weight

    @property
    def tare_weight_difference(self) -> int | None:
        return None if self.industry_tare_weight is None else self.industry_tare_weight - self.merchant_tare_weight

    @property
    def percentage_difference(self) -> Decimal | None:
        """Shortage as % of our weight; positive = the industry weighed less."""
        diff = self.difference_in_delivering_weight
        if diff is None:
            return None
        return (Decimal(-diff) * 100 / Decimal(self.merchant_net_weight)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # ---- money (rate, deduction, broker and grain come from the booking)
    @property
    def booking(self) -> BrokerBooking:
        return self.trip.broker_booking

    @property
    def effective_rate(self) -> int:
        return self.booking.grain_rate_per_booking_weight - self.any_rate_change

    @property
    def booking_weight(self) -> int:
        return self.booking.brokerage.grain.booking_weight

    @property
    def receivable_amount(self) -> int | None:
        """((industry net kg) / booking_weight) * (rate - any_rate_change). None until the industry weight is in."""
        n = self.industry_net_weight
        if n is None:
            return None
        return money.receivable_amount(n, self.booking_weight, self.booking.grain_rate_per_booking_weight, self.any_rate_change)

    @property
    def receivable_after_deduction(self) -> int | None:
        """receivable_amount * (1 - percentage_deduction / 100): what the industry is actually billed."""
        r = self.receivable_amount
        return None if r is None else money.receivable_after_percentage_deduction(r, self.booking.percentage_deduction)

    @property
    def estimated_amount(self) -> int:
        """What we expected to bill, from our own weight at the booked rate."""
        amount = money.receivable_amount(self.merchant_net_weight, self.booking_weight, self.booking.grain_rate_per_booking_weight, self.any_rate_change)
        return money.receivable_after_percentage_deduction(amount, self.booking.percentage_deduction)

    @property
    def error_receivable_amount(self) -> int | None:
        r = self.receivable_after_deduction
        return None if r is None else r - self.estimated_amount

    @property
    def brokerage_amount(self) -> int:
        """total_bags_in_truck * brokerage_per_bag (the broker's rate for this grain)."""
        return money.brokerage_amount(self.total_bags_in_truck, self.booking.brokerage.brokerage_per_bag)


class LabourWork(TimestampMixin, Base):
    """A labour group's day: what they earned, what they borrowed (deducted), and petrol/meal we covered (not deducted)."""

    __tablename__ = "labour_work"
    __table_args__ = (
        _year_check("labour_work"),
        _year_index("labour_work"),
        CheckConstraint("borrowing_amount <= payable_amount", name="ck_labour_work_borrowing_le_payable"),
        CheckConstraint(
            "payable_amount >= 0 AND borrowing_amount >= 0 AND petrol >= 0 AND meal >= 0",
            name="ck_labour_work_amount_nonneg",
        ),
        Index("ix_labour_work_labour_group_id", "labour_group_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    work_date: Mapped[date] = mapped_column(Date)
    labour_group_id: Mapped[int] = mapped_column(ForeignKey("labour_groups.id"))
    payable_amount: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    borrowing_amount: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    petrol: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    meal: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    business_year: Mapped[str] = mapped_column(String(7))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    labour_group: Mapped[LabourGroup] = relationship(lazy="joined")

    @property
    def net_payable(self) -> int:
        return self.payable_amount - self.borrowing_amount


class BagSupply(TimestampMixin, Base):
    """Bags a supplier delivered to a farmer's place. A business cost, never deducted from the farmer."""

    __tablename__ = "bag_supplies"
    __table_args__ = (
        _year_check("bag_supplies"),
        _year_index("bag_supplies"),
        CheckConstraint("rate_per_bag > 0 AND no_of_bags > 0", name="ck_bag_supplies_positive"),
        Index("ix_bag_supplies_farmer_id", "farmer_id"),
        Index("ix_bag_supplies_supplier_id", "supplier_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("bag_suppliers.id"))
    farmer_id: Mapped[int] = mapped_column(ForeignKey("farmers.id"))
    supply_date: Mapped[date] = mapped_column(Date)
    payable_amount: Mapped[int] = mapped_column(BigInteger)
    rate_per_bag: Mapped[int] = mapped_column(Integer)
    no_of_bags: Mapped[int] = mapped_column(Integer)
    business_year: Mapped[str] = mapped_column(String(7))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


    supplier: Mapped[BagSupplier] = relationship(lazy="joined")
    farmer: Mapped[Farmer] = relationship(lazy="joined")