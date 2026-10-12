"""Master (reference) tables. Running totals are deliberately absent: they are derived
from transaction/ledger rows, never stored."""

from sqlalchemy import CheckConstraint, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

MOBILE = r"^[0-9]{10}$"
TRUCK_NO = r"^[A-Z]{2}[0-9]{2}[A-Z]{1,2}[0-9]{4}$"


def _mobile_check(col: str, nullable: bool = False) -> CheckConstraint:
    expr = f"{col} ~ '{MOBILE}'"
    if nullable:
        expr = f"{col} IS NULL OR {expr}"
    return CheckConstraint(expr, name=f"ck_{col}_10_digits")


class Farmer(TimestampMixin, Base):
    __tablename__ = "farmers"
    __table_args__ = (
        _mobile_check("mobile"),
        _mobile_check("upi_number", nullable=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))  # surname person father grandfather
    name_gu: Mapped[str | None] = mapped_column(String(120))
    head_of_family: Mapped[str | None] = mapped_column(String(60))  # verify with before payment
    mobile: Mapped[str] = mapped_column(String(10), unique=True)
    email: Mapped[str | None] = mapped_column(String(60), unique=True)
    village: Mapped[str] = mapped_column(String(30))
    village_gu: Mapped[str | None] = mapped_column(String(30))
    house: Mapped[str | None] = mapped_column(Text)
    upi_number: Mapped[str | None] = mapped_column(String(10), unique=True)
    bank_account_number: Mapped[str | None] = mapped_column(String(30), unique=True)
    bank_name: Mapped[str | None] = mapped_column(String(30))
    bank_branch: Mapped[str | None] = mapped_column(String(30))
    ifsc_code: Mapped[str | None] = mapped_column(String(15))
    description: Mapped[str | None] = mapped_column(Text)  # owner-only
    public_figure: Mapped[str | None] = mapped_column(Text)


class BagSupplier(TimestampMixin, Base):
    __tablename__ = "bag_suppliers"
    __table_args__ = (
        _mobile_check("mobile"),
        _mobile_check("upi_number", nullable=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    name_gu: Mapped[str | None] = mapped_column(String(120))
    pet_name: Mapped[str] = mapped_column(String(30))
    mobile: Mapped[str] = mapped_column(String(10), unique=True)
    email: Mapped[str | None] = mapped_column(String(60), unique=True)
    upi_number: Mapped[str | None] = mapped_column(String(10), unique=True)


class LabourGroup(TimestampMixin, Base):
    __tablename__ = "labour_groups"
    __table_args__ = (_mobile_check("mobile"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))  # group leader
    name_gu: Mapped[str | None] = mapped_column(String(120))
    mobile: Mapped[str] = mapped_column(String(10), unique=True)
    group_name: Mapped[str] = mapped_column(String(30))
    group_name_gu: Mapped[str | None] = mapped_column(String(30))


class Transporter(TimestampMixin, Base):
    __tablename__ = "transporters"
    __table_args__ = (
        _mobile_check("mobile"),
        _mobile_check("upi_number", nullable=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    pet_name: Mapped[str] = mapped_column(String(30), unique=True)
    location: Mapped[str] = mapped_column(String(60))
    owner_name: Mapped[str] = mapped_column(String(120))
    owner_name_gu: Mapped[str | None] = mapped_column(String(120))
    mobile: Mapped[str] = mapped_column(String(10), unique=True)
    upi_number: Mapped[str | None] = mapped_column(String(10), unique=True)


class Truck(TimestampMixin, Base):
    __tablename__ = "trucks"
    __table_args__ = (
        CheckConstraint(f"truck_number ~ '{TRUCK_NO}'", name="ck_trucks_number_format"),
        _mobile_check("owner_mobile"),
        _mobile_check("driver_mobile"),
        _mobile_check("upi_number", nullable=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    truck_number: Mapped[str] = mapped_column(String(13), unique=True)  # GJ03AB1234, no spaces
    owner_name: Mapped[str] = mapped_column(String(120))
    owner_mobile: Mapped[str] = mapped_column(String(10))
    driver_name: Mapped[str] = mapped_column(String(120))
    driver_mobile: Mapped[str] = mapped_column(String(10))
    upi_number: Mapped[str | None] = mapped_column(String(10))
    description: Mapped[str | None] = mapped_column(Text)


class Industry(TimestampMixin, Base):
    __tablename__ = "industries"
    __table_args__ = (
        _mobile_check("owner_mobile"),
        _mobile_check("supervisor_mobile"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    name_gu: Mapped[str | None] = mapped_column(String(120))
    owner_name: Mapped[str] = mapped_column(String(120))
    owner_mobile: Mapped[str] = mapped_column(String(10))
    supervisor_name: Mapped[str] = mapped_column(String(120))
    supervisor_mobile: Mapped[str] = mapped_column(String(10))
    product: Mapped[str] = mapped_column(String(60))
    location: Mapped[str] = mapped_column(String(120))
    required_quality: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)


class Broker(TimestampMixin, Base):
    __tablename__ = "brokers"
    __table_args__ = (
        _mobile_check("mobile"),
        _mobile_check("upi_number", nullable=True),
        CheckConstraint("brokerage_per_truck >= 0", name="ck_brokers_brokerage_nonneg"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    name_gu: Mapped[str | None] = mapped_column(String(120))
    mobile: Mapped[str] = mapped_column(String(10), unique=True)
    brokerage_per_truck: Mapped[int] = mapped_column(Integer)  # rupees, fixed per truck
    upi_number: Mapped[str | None] = mapped_column(String(10), unique=True)


class Grain(TimestampMixin, Base):
    """Grain master plus its default terms & conditions and bag size options."""

    __tablename__ = "grains"
    __table_args__ = (
        CheckConstraint("default_net_weight IN (35, 50, 70, 100)", name="ck_grains_net_weight"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(30), unique=True)
    name_gu: Mapped[str | None] = mapped_column(String(30))
    default_net_weight: Mapped[int] = mapped_column(Integer)  # kg per bag
    default_terms: Mapped[str | None] = mapped_column(Text)  # clean, moisture, variety, ...
