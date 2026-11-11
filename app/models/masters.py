"""Master (reference) tables: file1-master1.txt and file2-master2.txt. Running totals are deliberately absent:
they are derived from transaction/ledger rows, never stored."""

from sqlalchemy import BigInteger, CheckConstraint, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

MOBILE = r"^[0-9]{10}$"
TRUCK_NO = r"^[A-Z]{2} [0-9]{2} (?: [A-Z]|[A-Z]{2}) [0-9]{4}$"  # GJ 01 DG 3345 / GJ 14  X 6720 (a one-letter series is padded to two columns)


def _digits_check(col: str, name: str | None = None, nullable: bool = False) -> CheckConstraint:
    expr = f"{col} ~ '{MOBILE}'"
    if nullable:
        expr = f"{col} IS NULL OR {expr}"
    return CheckConstraint(expr, name=name or f"ck_{col}_10_digits")


def _mobile_check(col: str = "mobile") -> CheckConstraint:
    return _digits_check(col)


def _upi_check() -> CheckConstraint:
    return _digits_check("upi_number", nullable=True)


# ---------------------------------------------------------------- file1-master1.txt
class EmptyBagSeller(TimestampMixin, Base):
    __tablename__ = "empty_bag_sellers"
    __table_args__ = (_upi_check(), _mobile_check())

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    name_gu: Mapped[str | None] = mapped_column(String(120))
    pet_name: Mapped[str] = mapped_column(String(30), unique=True)
    pet_name_gu: Mapped[str | None] = mapped_column(String(30))
    mobile: Mapped[str] = mapped_column(String(10), unique=True)
    upi_number: Mapped[str | None] = mapped_column(String(10), unique=True)
    description: Mapped[str | None] = mapped_column(Text)


class EmptyBagMover(TimestampMixin, Base):
    """Moves empty bags from a stockyard to a particular farmer's house (file1: empty_bag_movers)."""

    __tablename__ = "empty_bag_movers"
    __table_args__ = (_upi_check(), _mobile_check())

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    name_gu: Mapped[str | None] = mapped_column(String(120))
    pet_name: Mapped[str] = mapped_column(String(30), unique=True)
    pet_name_gu: Mapped[str | None] = mapped_column(String(30))
    mobile: Mapped[str] = mapped_column(String(10), unique=True)
    upi_number: Mapped[str | None] = mapped_column(String(10), unique=True)
    description: Mapped[str | None] = mapped_column(Text)


class Transporter(TimestampMixin, Base):
    __tablename__ = "transporters"
    __table_args__ = (_upi_check(), _mobile_check())

    id: Mapped[int] = mapped_column(primary_key=True)
    transporter_name: Mapped[str] = mapped_column(String(120), unique=True)
    pet_name: Mapped[str] = mapped_column(String(30), unique=True)
    pet_name_gu: Mapped[str] = mapped_column(String(30))
    location: Mapped[str] = mapped_column(String(60))
    owner_name: Mapped[str] = mapped_column(String(120))
    owner_name_gu: Mapped[str | None] = mapped_column(String(120))
    mobile: Mapped[str] = mapped_column(String(10), unique=True)
    upi_number: Mapped[str | None] = mapped_column(String(10), unique=True)
    description: Mapped[str | None] = mapped_column(Text)


class Truck(TimestampMixin, Base):
    __tablename__ = "trucks"
    __table_args__ = (
        _digits_check("truck_owner_upi_number", nullable=True),
        _digits_check("driver_upi_number", nullable=True),
        CheckConstraint(f"truck_number ~ '{TRUCK_NO}'", name="ck_trucks_number_format"),
        _digits_check("truck_owner_mobile", "ck_truck_owner_mobile_10_digits"),
        _digits_check("driver_mobile"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    truck_number: Mapped[str] = mapped_column(String(13), unique=True)  # GJ 03 AB 1234, with the spaces
    truck_owner_name: Mapped[str] = mapped_column(String(120))
    truck_owner_mobile: Mapped[str] = mapped_column(String(10))
    driver_name: Mapped[str] = mapped_column(String(120))
    driver_mobile: Mapped[str] = mapped_column(String(10))
    truck_owner_upi_number: Mapped[str | None] = mapped_column(String(10))
    driver_upi_number: Mapped[str | None] = mapped_column(String(10))
    description: Mapped[str | None] = mapped_column(Text)


class Industry(TimestampMixin, Base):
    __tablename__ = "industries"
    __table_args__ = (
        _digits_check("industry_owner_mobile", "ck_owner_mobile_10_digits"),
        _digits_check("supervisor_mobile"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    industry_name: Mapped[str] = mapped_column(String(120), unique=True)
    industry_name_gu: Mapped[str | None] = mapped_column(String(120))
    industry_owner_name: Mapped[str] = mapped_column(String(120))
    industry_owner_mobile: Mapped[str] = mapped_column(String(10))
    supervisor_name: Mapped[str] = mapped_column(String(120))
    supervisor_mobile: Mapped[str] = mapped_column(String(10))
    grain: Mapped[str] = mapped_column(String(60))
    location: Mapped[str] = mapped_column(String(120))
    quality_expectation: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)


class Broker(TimestampMixin, Base):
    __tablename__ = "brokers"
    __table_args__ = (_mobile_check(), _upi_check())

    id: Mapped[int] = mapped_column(primary_key=True)
    broker_name: Mapped[str] = mapped_column(String(120), unique=True)
    broker_name_gu: Mapped[str | None] = mapped_column(String(120))
    mobile: Mapped[str] = mapped_column(String(10), unique=True)
    upi_number: Mapped[str | None] = mapped_column(String(10), unique=True)
    description: Mapped[str | None] = mapped_column(Text)


class Village(TimestampMixin, Base):
    __tablename__ = "villages"

    id: Mapped[int] = mapped_column(primary_key=True)
    village_name: Mapped[str] = mapped_column(String(30), unique=True)
    village_name_gu: Mapped[str | None] = mapped_column(String(30))
    description: Mapped[str | None] = mapped_column(Text)


class LabourGroup(TimestampMixin, Base):
    """A labour group is named "group name - village name": the name is unique per village (groups saved before villages were added have none)."""

    __tablename__ = "labour_groups"
    __table_args__ = (
        UniqueConstraint("group_name", "village_id", name="uq_labour_groups_name_village"),
        Index("uq_labour_groups_name_no_village", "group_name", unique=True, postgresql_where=text("village_id IS NULL")),
        Index("ix_labour_groups_village_id", "village_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    group_name: Mapped[str] = mapped_column(String(30))
    group_name_gu: Mapped[str | None] = mapped_column(String(30))
    village_id: Mapped[int | None] = mapped_column(ForeignKey("villages.id"))
    description: Mapped[str | None] = mapped_column(Text)

    village: Mapped["Village | None"] = relationship(lazy="joined")

    @property
    def display_name(self) -> str:
        """What every list, drop-down and statement shows: "group name - village name"."""
        return f"{self.group_name} - {self.village.village_name}" if self.village else self.group_name

    @property
    def display_name_gu(self) -> str | None:
        gu = self.group_name_gu
        if gu and self.village and self.village.village_name_gu:
            return f"{gu} - {self.village.village_name_gu}"
        return gu


class Grain(TimestampMixin, Base):
    """Grain master: bag size (kg per filled bag), the weight unit it is booked in, and its default terms."""

    __tablename__ = "grains"
    __table_args__ = (
        CheckConstraint("net_bag_weight IN (35, 50, 70, 100)", name="ck_grains_net_bag_weight"),
        CheckConstraint("booking_weight IN (20, 100)", name="ck_grains_booking_weight"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    grain_name: Mapped[str] = mapped_column(String(30), unique=True)
    grain_name_gu: Mapped[str | None] = mapped_column(String(30))
    net_bag_weight: Mapped[int] = mapped_column(Integer)
    expected_raw_weight_per_bag: Mapped[float] = mapped_column(Float)
    booking_weight: Mapped[int] = mapped_column(Integer)
    grain_terms: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------- file2-master2.txt
class Farmer(TimestampMixin, Base):
    __tablename__ = "farmers"
    __table_args__ = (_mobile_check(), _upi_check(), Index("ix_farmers_village_id", "village_id"))

    id: Mapped[int] = mapped_column(primary_key=True)
    farmer_name: Mapped[str] = mapped_column(String(120))  # surname person father grandfather
    farmer_name_gu: Mapped[str | None] = mapped_column(String(120))
    head_of_family: Mapped[str | None] = mapped_column(String(100))  # ask him before payment: "Self", or surname (the farmer's own) + name + father's name
    mobile: Mapped[str] = mapped_column(String(10), unique=True)
    email: Mapped[str | None] = mapped_column(String(60), unique=True)
    village_id: Mapped[int] = mapped_column(ForeignKey("villages.id"))
    house: Mapped[str | None] = mapped_column(Text)
    upi_number: Mapped[str | None] = mapped_column(String(10), unique=True)
    bank_account_number: Mapped[str | None] = mapped_column(String(30), unique=True)
    bank_name: Mapped[str | None] = mapped_column(String(30))
    bank_branch: Mapped[str | None] = mapped_column(String(30))
    ifsc_code: Mapped[str | None] = mapped_column(String(15))
    private_note_owner_only: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)

    village: Mapped[Village] = relationship(lazy="joined")


class Labour(TimestampMixin, Base):
    __tablename__ = "labours"
    __table_args__ = (_mobile_check(), _upi_check(), Index("ix_labours_labour_group_id", "labour_group_id"))

    id: Mapped[int] = mapped_column(primary_key=True)
    labour_name: Mapped[str] = mapped_column(String(120))
    labour_name_gu: Mapped[str | None] = mapped_column(String(120))
    labour_group_id: Mapped[int] = mapped_column(ForeignKey("labour_groups.id"))
    mobile: Mapped[str] = mapped_column(String(10), unique=True)
    upi_number: Mapped[str | None] = mapped_column(String(10), unique=True)
    description: Mapped[str | None] = mapped_column(Text)

    labour_group: Mapped[LabourGroup] = relationship(lazy="joined")


class LabourGroupWage(TimestampMixin, Base):
    """Per-grain wage rates of a labour group (rupees per bag for each kind of work)."""

    __tablename__ = "labour_group_wages"
    __table_args__ = (
        CheckConstraint(
            "weighing_rate >= 0 AND loading_rate >= 0 AND pulling_rate >= 0 AND mixing_rate >= 0",
            name="ck_labour_group_wages_rate_nonneg",
        ),
        Index("ix_labour_group_wages_grain_id", "grain_id"),
        UniqueConstraint("labour_group_id", "grain_id", name="uq_labour_group_wages_group_grain"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    labour_group_id: Mapped[int] = mapped_column(ForeignKey("labour_groups.id"))
    grain_id: Mapped[int] = mapped_column(ForeignKey("grains.id"))
    weighing_rate: Mapped[int] = mapped_column(Integer)
    loading_rate: Mapped[int] = mapped_column(Integer)
    pulling_rate: Mapped[int] = mapped_column(Integer)
    mixing_rate: Mapped[int] = mapped_column(Integer)
    other_rate: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)

    labour_group: Mapped[LabourGroup] = relationship(lazy="joined")
    grain: Mapped[Grain] = relationship(lazy="joined")


class Brokerage(TimestampMixin, Base):
    """What a broker earns per bag for a grain."""

    __tablename__ = "brokerages"
    __table_args__ = (
        CheckConstraint("brokerage_per_bag >= 0", name="ck_brokerages_brokerage_nonneg"),
        Index("ix_brokerages_grain_id", "grain_id"),
        UniqueConstraint("broker_id", "grain_id", name="uq_brokerages_broker_grain"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    broker_id: Mapped[int] = mapped_column(ForeignKey("brokers.id"))
    grain_id: Mapped[int] = mapped_column(ForeignKey("grains.id"))
    brokerage_per_bag: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)

    broker: Mapped[Broker] = relationship(lazy="joined")
    grain: Mapped[Grain] = relationship(lazy="joined")


class Stockyard(TimestampMixin, Base):
    """A place where bought grain is stored; its owner is paid rent (owner 'Self' when it is ours)."""

    __tablename__ = "stockyards"
    __table_args__ = (
        CheckConstraint("rent_of_stockyard >= 0", name="ck_stockyards_rent_of_stockyard_nonneg"),
        _digits_check("stockyard_owner_mobile", name="ck_stockyards_owner_mobile_10_digits"),
        _digits_check("stockyard_upi_number", name="ck_stockyards_upi_number_10_digits", nullable=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name_of_stockyard: Mapped[str] = mapped_column(Text)
    location: Mapped[str] = mapped_column(Text)
    stockyard_owner_name: Mapped[str] = mapped_column(String(120), default="Self", server_default="Self")
    stockyard_owner_mobile: Mapped[str] = mapped_column(String(10))
    stockyard_upi_number: Mapped[str | None] = mapped_column(String(10))
    storage_capacity: Mapped[int] = mapped_column(BigInteger)
    rent_of_stockyard: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    description: Mapped[str | None] = mapped_column(Text)
