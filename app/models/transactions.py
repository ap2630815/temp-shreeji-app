"""Form tables (file4-transactional.txt): records entered through the data-entry forms.

Whole rupees (BigInteger) and integer kg. Every dated record carries a business_year (1 Oct - 30 Sep, e.g. '2025-26'),
set by the application from the record's own date (file9-database.txt, rule 5)."""

from datetime import date

from sqlalchemy import BigInteger, CheckConstraint, Date, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

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
