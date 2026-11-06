"""Form tables (file4-transactional.txt): records entered through the data-entry forms.

Whole rupees (BigInteger) and integer kg. Every dated record carries a business_year (1 Oct - 30 Sep, e.g. '2025-26'),
set by the application from the record's own date (file9-database.txt, rule 5)."""

from datetime import date

from sqlalchemy import BigInteger, CheckConstraint, Date, Float, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint, text
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import cast, func, or_, select
from sqlalchemy.orm import Mapped, aliased, column_property, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.masters import Brokerage, EmptyBagMover, Farmer, Grain, Industry, LabourGroup, EmptyBagSeller, Stockyard, Transporter, Truck, Village
from app.services import money

BUSINESS_YEAR = r"^[0-9]{4}-[0-9]{2}$"


def _year_check(table: str) -> CheckConstraint:
    return CheckConstraint(f"business_year ~ '{BUSINESS_YEAR}'", name=f"ck_{table}_business_year_format")


def _year_index(table: str) -> Index:
    return Index(f"ix_{table}_business_year", "business_year")


class PurchaseGroup(TimestampMixin, Base):
    """One deal: a few farmers of a village gather and agree one grain, one rate and the terms (listed in
    purchase_group_add_farmers). A village has many of these over time."""

    __tablename__ = "purchase_groups"
    __table_args__ = (
        _year_check("purchase_group"),
        _year_index("purchase_group"),
        CheckConstraint("grain_rate_per_20kg > 0", name="ck_purchase_group_rate_positive"),
        CheckConstraint("pay_after_no_of_days >= 0", name="ck_purchase_group_pay_after"),
        Index("ix_purchase_group_village_id", "village_id"),
        Index("ix_purchase_group_grain_id", "grain_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_group_date: Mapped[date] = mapped_column(Date)
    village_id: Mapped[int] = mapped_column(ForeignKey("villages.id"))
    grain_id: Mapped[int] = mapped_column(ForeignKey("grains.id"))
    grain_rate_per_20kg: Mapped[int] = mapped_column(Integer)
    pay_after_no_of_days: Mapped[int] = mapped_column(Integer)
    purchase_group_terms: Mapped[str | None] = mapped_column(Text)
    business_year: Mapped[str] = mapped_column(String(7))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    village: Mapped[Village] = relationship(lazy="joined")
    grain: Mapped[Grain] = relationship(lazy="joined")


class PurchaseGroupFarmer(TimestampMixin, Base):
    """A farmer who took part in one purchase_group (deal). His ledger for that deal is his purchase_group_farmers_entries."""

    __tablename__ = "purchase_group_add_farmers"
    __table_args__ = (
        UniqueConstraint("purchase_group_id", "farmer_id", name="uq_purchase_group_add_farmers_info_farmer"),
        Index("ix_purchase_group_add_farmers_farmer_id", "farmer_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_group_id: Mapped[int] = mapped_column(ForeignKey("purchase_groups.id"))
    farmer_id: Mapped[int] = mapped_column(ForeignKey("farmers.id"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    purchase_group: Mapped[PurchaseGroup] = relationship(lazy="joined")
    farmer: Mapped[Farmer] = relationship(lazy="joined")


class PurchaseFarmerEntry(TimestampMixin, Base):
    """One farmer's weighed grain inside a purchase_group. Rate, grain and pay-after come from the purchase_group."""

    __tablename__ = "purchase_group_farmers_entries"
    __table_args__ = (
        _year_check("purchase_group_farmers_entries"),
        _year_index("purchase_group_farmers_entries"),
        CheckConstraint("extra_kilos >= 0", name="ck_purchase_group_farmers_entries_extra_kilos"),
        CheckConstraint("no_of_filled_bags >= 0", name="ck_purchase_group_farmers_entries_no_of_filled_bags"),
        CheckConstraint("payable_amount >= 0", name="ck_purchase_group_farmers_entries_payable_amount"),
        CheckConstraint("borrowed_amount >= 0", name="ck_purchase_group_farmers_entries_borrowed_amount"),
        CheckConstraint("borrowed_amount <= payable_amount", name="ck_purchase_group_farmers_entries_borrowed_amount_le_payable_amount"),
        CheckConstraint("expected_raw_weight_per_bag >= 0", name="ck_purchase_group_farmers_entries_expected_raw_weight_per_bag"),
        CheckConstraint("no_of_handful_bags >= 0", name="ck_purchase_group_farmers_entries_no_of_handful_bags"),
        CheckConstraint("total_available_bags >= 0", name="ck_purchase_group_farmers_entries_total_available_bags"),
        Index("ix_purchase_group_farmers_entries_purchase_group_id", "purchase_group_id"),
        Index("ix_purchase_group_farmers_entries_farmer_id", "farmer_id"),
        Index("ix_purchase_group_farmers_entries_labour_group_id", "labour_group_id"),
        ForeignKeyConstraint(
            ["purchase_group_id", "farmer_id"],
            ["purchase_group_add_farmers.purchase_group_id", "purchase_group_add_farmers.farmer_id"],
            name="fk_purchase_group_farmers_entries_listed_farmer",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_entry_date: Mapped[date] = mapped_column(Date)
    purchase_group_id: Mapped[int] = mapped_column(ForeignKey("purchase_groups.id"))
    farmer_id: Mapped[int] = mapped_column(ForeignKey("farmers.id"))
    labour_group_id: Mapped[int] = mapped_column(ForeignKey("labour_groups.id"))
    no_of_filled_bags: Mapped[int] = mapped_column(Integer)
    extra_kilos: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    payable_amount: Mapped[int] = mapped_column(BigInteger)
    borrowed_amount: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    due_date: Mapped[date] = mapped_column(Date)
    expected_raw_weight_per_bag: Mapped[float] = mapped_column(Float)  # starts at the grain's expected_raw_weight_per_bag, editable
    grain_quality_code: Mapped[str | None] = mapped_column(Text)
    grain_stored_location: Mapped[str | None] = mapped_column(Text)
    no_of_handful_bags: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_available_bags: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    business_year: Mapped[str] = mapped_column(String(7))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    purchase_group: Mapped[PurchaseGroup] = relationship(lazy="joined")
    farmer: Mapped[Farmer] = relationship(lazy="joined")
    labour_group: Mapped[LabourGroup] = relationship(lazy="joined")

    @property
    def net_payable(self) -> int:
        """payable_amount - borrowed_amount: what the farmer is still to be paid."""
        return self.payable_amount - self.borrowed_amount

    @property
    def total_kg(self) -> int:
        return self.no_of_filled_bags * self.purchase_group.grain.net_bag_weight + self.extra_kilos

    # ---- the same names a PurchaseIndividual has, so the farmer ledger can list both kinds of entry together
    is_direct = False

    @property
    def village_id(self) -> int:
        return self.purchase_group.village_id

    @property
    def village(self) -> Village:
        return self.purchase_group.village

    @property
    def entry_date(self) -> date:
        return self.purchase_entry_date

    @property
    def grain(self) -> Grain:
        return self.purchase_group.grain

    @property
    def grain_rate_per_20kg(self) -> int:
        return self.purchase_group.grain_rate_per_20kg

    @property
    def pay_after_no_of_days(self) -> int:
        return self.purchase_group.pay_after_no_of_days


class PurchaseIndividual(TimestampMixin, Base):
    """A farmer entry made directly on the farmer ledger, on one form, without a purchase_group.

    It carries the purchase_group columns (date, village, grain, rate, pay-after, terms) and the purchase_group_farmers_entries
    columns (farmer, labour group, bags, amounts...) in one row, with ONE description. Its money is paid through the
    same farmer payments as any other entry (payment_allocations.payable_type = 'purchase_individual')."""

    __tablename__ = "purchase_individuals"
    __table_args__ = (
        _year_check("purchase_individuals"),
        _year_index("purchase_individuals"),
        CheckConstraint("grain_rate_per_20kg > 0", name="ck_purchase_individuals_rate_positive"),
        CheckConstraint("pay_after_no_of_days >= 0", name="ck_purchase_individuals_pay_after"),
        CheckConstraint("extra_kilos >= 0", name="ck_purchase_individuals_extra_kilos"),
        CheckConstraint("no_of_filled_bags >= 0", name="ck_purchase_individuals_no_of_filled_bags"),
        CheckConstraint("payable_amount >= 0", name="ck_purchase_individuals_payable_amount"),
        CheckConstraint("borrowed_amount >= 0", name="ck_purchase_individuals_borrowed_amount"),
        CheckConstraint("borrowed_amount <= payable_amount", name="ck_purchase_individuals_borrowed_amount_le_payable_amount"),
        CheckConstraint("expected_raw_weight_per_bag >= 0", name="ck_purchase_individuals_expected_raw_weight_per_bag"),
        CheckConstraint("no_of_handful_bags >= 0", name="ck_purchase_individuals_no_of_handful_bags"),
        CheckConstraint("total_available_bags >= 0", name="ck_purchase_individuals_total_available_bags"),
        Index("ix_purchase_individuals_farmer_id", "farmer_id"),
        Index("ix_purchase_individuals_village_id", "village_id"),
        Index("ix_purchase_individuals_grain_id", "grain_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # ---- the purchase_group columns
    purchase_individual_date: Mapped[date] = mapped_column(Date)
    village_id: Mapped[int] = mapped_column(ForeignKey("villages.id"))
    grain_id: Mapped[int] = mapped_column(ForeignKey("grains.id"))
    grain_rate_per_20kg: Mapped[int] = mapped_column(Integer)
    pay_after_no_of_days: Mapped[int] = mapped_column(Integer)
    terms: Mapped[str | None] = mapped_column(Text)
    # ---- the purchase_group_farmers_entries columns
    farmer_id: Mapped[int] = mapped_column(ForeignKey("farmers.id"))
    labour_group_id: Mapped[int] = mapped_column(ForeignKey("labour_groups.id"))
    no_of_filled_bags: Mapped[int] = mapped_column(Integer)
    extra_kilos: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    no_of_handful_bags: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_available_bags: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    payable_amount: Mapped[int] = mapped_column(BigInteger)
    borrowed_amount: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    due_date: Mapped[date] = mapped_column(Date)
    expected_raw_weight_per_bag: Mapped[float] = mapped_column(Float)  # starts at the grain's expected_raw_weight_per_bag, editable
    grain_quality_code: Mapped[str | None] = mapped_column(Text)
    grain_stored_location: Mapped[str | None] = mapped_column(Text)
    # ---- shared by both
    business_year: Mapped[str] = mapped_column(String(7))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    village: Mapped[Village] = relationship(lazy="joined")
    grain: Mapped[Grain] = relationship(lazy="joined")
    farmer: Mapped[Farmer] = relationship(lazy="joined")
    labour_group: Mapped[LabourGroup] = relationship(lazy="joined")

    is_direct = True

    @property
    def entry_date(self) -> date:
        return self.purchase_individual_date

    purchase_group = None  # a direct entry belongs to no purchase
    purchase_group_id = None

    @property
    def net_payable(self) -> int:
        return self.payable_amount - self.borrowed_amount

    @property
    def total_kg(self) -> int:
        return self.no_of_filled_bags * self.grain.net_bag_weight + self.extra_kilos


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
    load_lines: Mapped[list["FarmersTruckLoadLine"]] = relationship(lazy="selectin", order_by="FarmersTruckLoadLine.id")
    stockyard_lines: Mapped[list["StockyardTruckLoadLine"]] = relationship(lazy="selectin", order_by="StockyardTruckLoadLine.id")

    @property
    def industry(self) -> Industry:
        return self.broker_booking.industry

    @property
    def grain(self) -> Grain:
        return self.broker_booking.brokerage.grain

    @property
    def bags(self) -> int:
        """total_bags_in_truck: the sum of the loaded bags over the trip's farmer load lines and stockyard load lines."""
        return sum(line.no_of_loaded_bags for line in self.load_lines) + sum(line.no_of_loaded_bags for line in self.stockyard_lines)

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


class FarmersTruckLoadLine(Base):
    """Bags of one farmer entry (a purchase_group_farmers_entries row OR a purchase_individuals row) loaded on one trip
    (no date of its own: it belongs to its trip's year)."""

    __tablename__ = "farmers_truck_load_lines"
    __table_args__ = (
        CheckConstraint("no_of_loaded_bags > 0", name="ck_farmers_truck_load_lines_no_of_loaded_bags"),
        CheckConstraint(
            "(purchase_farmer_entry_id IS NOT NULL AND purchase_individual_id IS NULL) OR (purchase_farmer_entry_id IS NULL AND purchase_individual_id IS NOT NULL)",
            name="ck_farmers_truck_load_lines_one_source",
        ),
        Index("ix_farmers_truck_load_lines_purchase_farmer_entry_id", "purchase_farmer_entry_id"),
        Index("ix_farmers_truck_load_lines_purchase_individual_id", "purchase_individual_id"),
        UniqueConstraint("trip_id", "purchase_farmer_entry_id", name="uq_farmers_truck_load_lines_trip_entry"),
        UniqueConstraint("trip_id", "purchase_individual_id", name="uq_farmers_truck_load_lines_trip_individual"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("truck_trips.id"))
    purchase_farmer_entry_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_group_farmers_entries.id"))
    purchase_individual_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_individuals.id"))
    no_of_loaded_bags: Mapped[int] = mapped_column(Integer)

    group_entry: Mapped[PurchaseFarmerEntry | None] = relationship(lazy="joined")
    individual: Mapped[PurchaseIndividual | None] = relationship(lazy="joined")

    @property
    def entry(self) -> PurchaseFarmerEntry | PurchaseIndividual:
        """The farmer entry the bags came from (either kind: both expose farmer, village, entry_date, grain...)."""
        return self.group_entry if self.purchase_farmer_entry_id is not None else self.individual


class StockyardTruckLoadLine(Base):
    """Bags loaded on one trip straight from a stockyard's stock of one grain. Stockyard stock is a big pool, so a line
    names the stockyard only, never a farmer."""

    __tablename__ = "stockyard_truck_load_lines"
    __table_args__ = (
        CheckConstraint("no_of_loaded_bags > 0", name="ck_stockyard_truck_load_lines_no_of_loaded_bags"),
        Index("ix_stockyard_truck_load_lines_stockyard_id", "stockyard_id"),
        UniqueConstraint("trip_id", "stockyard_id", name="uq_stockyard_truck_load_lines_trip_stockyard"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("truck_trips.id"))
    stockyard_id: Mapped[int] = mapped_column(ForeignKey("stockyards.id"))
    no_of_loaded_bags: Mapped[int] = mapped_column(Integer)

    stockyard: Mapped[Stockyard] = relationship(lazy="joined")
    # The grain is the trip's grain (trip -> booking -> brokerage -> grain) and the expected raw weight per bag is worked out from the
    # purchases that filled the stockyard: neither is stored on the line (see expected_raw_weight_per_bag at the end of this module).


class FarmerStockyardTransfer(TimestampMixin, Base):
    """Filled bags brought from a farmer's place (all or part of an entry's available bags) to a stockyard."""

    __tablename__ = "farmer_to_stockyard_transfers"
    __table_args__ = (
        _year_check("farmer_stockyard_transfers"),
        _year_index("farmer_stockyard_transfers"),
        CheckConstraint("no_of_transferred_bags > 0", name="ck_farmer_stockyard_transfers_no_of_bags"),
        CheckConstraint(
            "(purchase_farmer_entry_id IS NOT NULL AND purchase_individual_id IS NULL) OR (purchase_farmer_entry_id IS NULL AND purchase_individual_id IS NOT NULL)",
            name="ck_farmer_stockyard_transfers_one_source",
        ),
        Index("ix_farmer_stockyard_transfers_purchase_farmer_entry_id", "purchase_farmer_entry_id"),
        Index("ix_farmer_stockyard_transfers_purchase_individual_id", "purchase_individual_id"),
        Index("ix_farmer_stockyard_transfers_stockyard_id", "stockyard_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    transfer_date: Mapped[date] = mapped_column(Date)
    purchase_farmer_entry_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_group_farmers_entries.id"))
    purchase_individual_id: Mapped[int | None] = mapped_column(ForeignKey("purchase_individuals.id"))
    stockyard_id: Mapped[int] = mapped_column(ForeignKey("stockyards.id"))
    no_of_transferred_bags: Mapped[int] = mapped_column(Integer)
    business_year: Mapped[str] = mapped_column(String(7))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    group_entry: Mapped[PurchaseFarmerEntry | None] = relationship(lazy="joined")
    individual: Mapped[PurchaseIndividual | None] = relationship(lazy="joined")
    stockyard: Mapped[Stockyard] = relationship(lazy="joined")

    @property
    def entry(self) -> PurchaseFarmerEntry | PurchaseIndividual:
        return self.group_entry if self.purchase_farmer_entry_id is not None else self.individual

    @property
    def grain(self) -> Grain:
        return self.entry.grain


class EmptyBag(TimestampMixin, Base):
    """Empty bags of one grain bought into a stockyard's pool (file4: empty_bags): from a seller, carried in by a mover.
    Bags used up by stockyard purchase entries are not recorded here: they are worked out from the entries."""

    __tablename__ = "empty_bags"
    __table_args__ = (
        _year_check("empty_bags"),
        _year_index("empty_bags"),
        CheckConstraint("no_of_empty_bags > 0", name="ck_empty_bags_no_of_empty_bags"),
        Index("ix_empty_bags_stockyard_id", "stockyard_id"),
        Index("ix_empty_bags_grain_id", "grain_id"),
        Index("ix_empty_bags_empty_bag_seller_id", "empty_bag_seller_id"),
        Index("ix_empty_bags_empty_bag_mover_id", "empty_bag_mover_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    empty_bags_entry_date: Mapped[date] = mapped_column(Date)
    stockyard_id: Mapped[int] = mapped_column(ForeignKey("stockyards.id"))
    grain_id: Mapped[int] = mapped_column(ForeignKey("grains.id"))
    empty_bag_seller_id: Mapped[int | None] = mapped_column(ForeignKey("empty_bag_sellers.id"))
    empty_bag_mover_id: Mapped[int | None] = mapped_column(ForeignKey("empty_bag_movers.id"))
    no_of_empty_bags: Mapped[int] = mapped_column(Integer)
    business_year: Mapped[str] = mapped_column(String(7))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    stockyard: Mapped[Stockyard] = relationship(lazy="joined")
    grain: Mapped[Grain] = relationship(lazy="joined")
    seller: Mapped[EmptyBagSeller | None] = relationship(lazy="joined")
    mover: Mapped[EmptyBagMover | None] = relationship(lazy="joined")


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
            + [(line.no_of_loaded_bags, line.expected_raw_weight_per_bag) for line in self.trip.stockyard_lines]
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


class EmptyBagSellerEntry(TimestampMixin, Base):
    """Bags a supplier delivered to a farmer's place. A business cost, never deducted from the farmer."""

    __tablename__ = "empty_bag_sellers_entries"
    __table_args__ = (
        _year_check("empty_bag_sellers"),
        _year_index("empty_bag_sellers"),
        CheckConstraint("rate_per_bag > 0 AND no_of_empty_bags > 0", name="ck_empty_bag_sellers_positive"),
        Index("ix_empty_bag_sellers_farmer_id", "farmer_id"),
        Index("ix_empty_bag_sellers_empty_bag_seller_id", "empty_bag_seller_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    empty_bag_seller_id: Mapped[int] = mapped_column(ForeignKey("empty_bag_sellers.id"))
    farmer_id: Mapped[int] = mapped_column(ForeignKey("farmers.id"))
    selling_date: Mapped[date] = mapped_column(Date)
    payable_amount: Mapped[int] = mapped_column(BigInteger)
    rate_per_bag: Mapped[int] = mapped_column(Integer)
    no_of_empty_bags: Mapped[int] = mapped_column(Integer)
    business_year: Mapped[str] = mapped_column(String(7))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


    supplier: Mapped[EmptyBagSeller] = relationship(lazy="joined")
    farmer: Mapped[Farmer] = relationship(lazy="joined")

class EmptyBagMoverEntry(TimestampMixin, Base):
    """Empty bags a mover carried from a stockyard to a farmer's house. A business cost (empty_bag_movers tab of file4)."""

    __tablename__ = "empty_bag_movers_entries"
    __table_args__ = (
        _year_check("empty_bag_movers"),
        _year_index("empty_bag_movers"),
        CheckConstraint("cost_per_mover > 0 AND no_of_empty_bags > 0", name="ck_empty_bag_movers_positive"),
        Index("ix_empty_bag_movers_farmer_id", "farmer_id"),
        Index("ix_empty_bag_movers_empty_bag_mover_id", "empty_bag_mover_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    empty_bag_mover_id: Mapped[int] = mapped_column(ForeignKey("empty_bag_movers.id"))
    farmer_id: Mapped[int] = mapped_column(ForeignKey("farmers.id"))
    mover_date: Mapped[date] = mapped_column(Date)
    cost_per_mover: Mapped[int] = mapped_column(Integer)
    no_of_empty_bags: Mapped[int] = mapped_column(Integer)
    business_year: Mapped[str] = mapped_column(String(7))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    mover: Mapped[EmptyBagMover] = relationship(lazy="joined")
    farmer: Mapped[Farmer] = relationship(lazy="joined")


class StockyardPurchase(TimestampMixin, Base):
    """One deal with a farmer for grain kept at a stockyard: grain, rate and pay-after are agreed here and its entries (weighed lots) follow."""

    __tablename__ = "stockyard_purchases"
    __table_args__ = (
        _year_check("stockyard_purchases"),
        _year_index("stockyard_purchases"),
        CheckConstraint("grain_rate_per_20kg > 0", name="ck_stockyard_purchases_rate_positive"),
        CheckConstraint("pay_after_no_of_days >= 0", name="ck_stockyard_purchases_pay_after"),
        CheckConstraint("no_of_given_empty_bags >= 0", name="ck_stockyard_purchases_no_of_given_empty_bags"),
        Index("ix_stockyard_purchases_stockyard_id", "stockyard_id"),
        Index("ix_stockyard_purchases_farmer_id", "farmer_id"),
        Index("ix_stockyard_purchases_grain_id", "grain_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    stockyard_purchase_date: Mapped[date] = mapped_column(Date)
    stockyard_id: Mapped[int] = mapped_column(ForeignKey("stockyards.id"))
    farmer_id: Mapped[int] = mapped_column(ForeignKey("farmers.id"))
    grain_id: Mapped[int] = mapped_column(ForeignKey("grains.id"))
    grain_rate_per_20kg: Mapped[int] = mapped_column(Integer)
    pay_after_no_of_days: Mapped[int] = mapped_column(Integer)
    no_of_given_empty_bags: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    terms: Mapped[str | None] = mapped_column(Text)
    business_year: Mapped[str] = mapped_column(String(7))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    stockyard: Mapped[Stockyard] = relationship(lazy="joined")
    farmer: Mapped[Farmer] = relationship(lazy="joined")
    grain: Mapped[Grain] = relationship(lazy="joined")


class StockyardPurchaseEntry(TimestampMixin, Base):
    """One weighed lot of a stockyard purchase. Grain, rate and pay-after come from the purchase."""

    __tablename__ = "stockyard_purchase_entries"
    __table_args__ = (
        _year_check("stockyard_purchase_entries"),
        _year_index("stockyard_purchase_entries"),
        CheckConstraint("no_of_filled_bags >= 0", name="ck_stockyard_purchase_entries_no_of_filled_bags"),
        CheckConstraint("extra_kilos >= 0", name="ck_stockyard_purchase_entries_extra_kilos"),
        CheckConstraint("no_of_received_empty_bags >= 0", name="ck_stockyard_purchase_entries_no_of_received_empty_bags"),
        CheckConstraint("payable_amount >= 0", name="ck_stockyard_purchase_entries_payable_amount"),
        CheckConstraint("borrowed_amount >= 0", name="ck_stockyard_purchase_entries_borrowed_amount"),
        CheckConstraint("borrowed_amount <= payable_amount", name="ck_stockyard_purchase_entries_borrowed_amount_le_payable_amount"),
        CheckConstraint("expected_raw_weight_per_bag >= 0", name="ck_stockyard_purchase_entries_expected_raw_weight_per_bag"),
        Index("ix_stockyard_purchase_entries_stockyard_purchase_id", "stockyard_purchase_id"),
        Index("ix_stockyard_purchase_entries_labour_group_id", "labour_group_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    stockyard_purchase_entry_date: Mapped[date] = mapped_column(Date)
    stockyard_purchase_id: Mapped[int] = mapped_column(ForeignKey("stockyard_purchases.id"))
    no_of_filled_bags: Mapped[int] = mapped_column(Integer)
    extra_kilos: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    payable_amount: Mapped[int] = mapped_column(BigInteger)
    borrowed_amount: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    due_date: Mapped[date] = mapped_column(Date)
    expected_raw_weight_per_bag: Mapped[float] = mapped_column(Float)  # starts at the grain's expected_raw_weight_per_bag, editable
    grain_quality_code: Mapped[str | None] = mapped_column(Text)
    no_of_received_empty_bags: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # starts at given - filled, editable
    labour_group_id: Mapped[int | None] = mapped_column(ForeignKey("labour_groups.id"))
    business_year: Mapped[str] = mapped_column(String(7))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    purchase: Mapped[StockyardPurchase] = relationship(lazy="joined")
    labour_group: Mapped[LabourGroup | None] = relationship(lazy="joined")

    @property
    def net_payable(self) -> int:
        """payable_amount - borrowed_amount: what the farmer is still to be paid."""
        return self.payable_amount - self.borrowed_amount

    @property
    def total_kg(self) -> int:
        return self.no_of_filled_bags * self.purchase.grain.net_bag_weight + self.extra_kilos


class StockyardArrangementEntry(TimestampMixin, Base):
    """Arranging (stacking) bags at the stockyard, paid per bag to a labour group; may belong to one purchase entry."""

    __tablename__ = "stockyard_arrangement_entries"
    __table_args__ = (
        _year_check("stockyard_arrangement_entries"),
        _year_index("stockyard_arrangement_entries"),
        CheckConstraint("no_of_arranged_bags > 0", name="ck_stockyard_arrangement_entries_no_of_arranged_bags"),
        CheckConstraint("rate_per_arranged_bag BETWEEN 1 AND 20", name="ck_stockyard_arrangement_entries_rate"),
        Index("ix_stockyard_arrangement_entries_purchase_entry_id", "stockyard_purchase_entry_id"),
        Index("ix_stockyard_arrangement_entries_labour_group_id", "labour_group_id"),
        Index("uq_stockyard_arrangement_entries_purchase_entry", "stockyard_purchase_entry_id", unique=True,
              postgresql_where=text("stockyard_purchase_entry_id IS NOT NULL")),  # a purchase entry is arranged only once
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    stockyard_arrangement_date: Mapped[date] = mapped_column(Date)
    stockyard_purchase_entry_id: Mapped[int | None] = mapped_column(ForeignKey("stockyard_purchase_entries.id"))
    labour_group_id: Mapped[int | None] = mapped_column(ForeignKey("labour_groups.id"))
    no_of_arranged_bags: Mapped[int] = mapped_column(Integer)
    rate_per_arranged_bag: Mapped[int] = mapped_column(Integer)
    business_year: Mapped[str] = mapped_column(String(7))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    purchase_entry: Mapped[StockyardPurchaseEntry | None] = relationship(lazy="joined")
    labour_group: Mapped[LabourGroup | None] = relationship(lazy="joined")

    @property
    def amount(self) -> int:
        return self.no_of_arranged_bags * self.rate_per_arranged_bag


def _stockyard_line_expected_weight():
    """Expected raw weight per bag of a stockyard load line: the average over the filled bags that came into that stockyard with the
    trip's grain, each purchase weighted by its bags (stockyard purchase entries, and the farmer purchases brought in by
    farmer_stockyard_transfers). Purchases without an expected weight are left out; None when no purchase has one."""
    line, transfers = StockyardTruckLoadLine, FarmerStockyardTransfer
    grain = (select(Brokerage.grain_id).join(BrokerBooking, BrokerBooking.brokerage_id == Brokerage.id).join(TruckTrip, TruckTrip.broker_booking_id == BrokerBooking.id)
             .where(TruckTrip.id == line.trip_id).correlate(line).scalar_subquery())
    sources = [  # (bags, expected weight, joins/filters)
        (StockyardPurchaseEntry.no_of_filled_bags, StockyardPurchaseEntry.expected_raw_weight_per_bag,
         lambda q: q.join(StockyardPurchase, StockyardPurchase.id == StockyardPurchaseEntry.stockyard_purchase_id)
         .where(StockyardPurchase.stockyard_id == line.stockyard_id, StockyardPurchase.grain_id == grain)),
        (transfers.no_of_transferred_bags, PurchaseFarmerEntry.expected_raw_weight_per_bag,
         lambda q: q.select_from(transfers).join(PurchaseFarmerEntry, PurchaseFarmerEntry.id == transfers.purchase_farmer_entry_id)
         .join(PurchaseGroup, PurchaseGroup.id == PurchaseFarmerEntry.purchase_group_id)
         .where(transfers.stockyard_id == line.stockyard_id, PurchaseGroup.grain_id == grain)),
        (transfers.no_of_transferred_bags, PurchaseIndividual.expected_raw_weight_per_bag,
         lambda q: q.select_from(transfers).join(PurchaseIndividual, PurchaseIndividual.id == transfers.purchase_individual_id)
         .where(transfers.stockyard_id == line.stockyard_id, PurchaseIndividual.grain_id == grain)),
    ]
    weighted, bags = 0, 0
    for n, w, where in sources:
        weighted = weighted + func.coalesce(where(select(func.sum(n * w))).scalar_subquery(), 0)
        bags = bags + func.coalesce(where(select(func.sum(n)).where(w.is_not(None))).scalar_subquery(), 0)
    return cast(weighted, Float) / func.nullif(bags, 0)  # float division


StockyardTruckLoadLine.expected_raw_weight_per_bag = column_property(_stockyard_line_expected_weight())


def _farmer_line_remaining():
    """farmers_truck_load_lines.total_remaining_bags (not stored): bags still at the farmer right after this line =
    the entry's total_available_bags - bags taken to a stockyard - bags loaded so far (this entry's lines up to this one, in id order)."""
    line, later, t = FarmersTruckLoadLine, aliased(FarmersTruckLoadLine), FarmerStockyardTransfer
    available = func.coalesce(
        select(PurchaseFarmerEntry.total_available_bags).where(PurchaseFarmerEntry.id == line.purchase_farmer_entry_id).correlate(line).scalar_subquery(),
        select(PurchaseIndividual.total_available_bags).where(PurchaseIndividual.id == line.purchase_individual_id).correlate(line).scalar_subquery(), 0)
    moved = func.coalesce(select(func.sum(t.no_of_transferred_bags)).where(
        or_(t.purchase_farmer_entry_id == line.purchase_farmer_entry_id, t.purchase_individual_id == line.purchase_individual_id)).correlate(line).scalar_subquery(), 0)
    loaded = func.coalesce(select(func.sum(later.no_of_loaded_bags)).where(
        or_(later.purchase_farmer_entry_id == line.purchase_farmer_entry_id, later.purchase_individual_id == line.purchase_individual_id), later.id <= line.id)
        .correlate(line).scalar_subquery(), 0)
    return func.greatest(available - moved - loaded, 0)


FarmersTruckLoadLine.total_remaining_bags = column_property(_farmer_line_remaining())
