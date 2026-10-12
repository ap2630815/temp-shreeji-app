"""Village purchase flow: commencing -> farmer weighing entries -> payments.

All money is whole rupees (BigInteger). Paid / due / status are never stored: they are derived from
payment_allocations, so the ledger cannot drift out of sync with the entries."""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.masters import Farmer, Grain, LabourGroup


class Commencing(TimestampMixin, Base):
    """A village deal: the whole village sells one grain at one rate on agreed terms."""

    __tablename__ = "commencings"
    __table_args__ = (
        CheckConstraint("rate_per_20kg > 0", name="ck_commencings_rate_positive"),
        CheckConstraint("net_weight IN (35, 50, 70, 100)", name="ck_commencings_net_weight"),
        CheckConstraint("pay_after_days >= 0", name="ck_commencings_pay_after"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    business_year: Mapped[str] = mapped_column(String(7), index=True)
    commencing_date: Mapped[date] = mapped_column(Date)
    village: Mapped[str] = mapped_column(String(100))
    grain_id: Mapped[int] = mapped_column(ForeignKey("grains.id"))
    rate_per_20kg: Mapped[int] = mapped_column(Integer)
    net_weight: Mapped[int] = mapped_column(Integer)  # kg per filled bag
    pay_after_days: Mapped[int] = mapped_column(Integer)
    terms: Mapped[str | None] = mapped_column(Text)  # snapshot of the grain's terms at agreement time
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    grain: Mapped[Grain] = relationship(lazy="joined")


class PurchaseEntry(TimestampMixin, Base):
    """One farmer's weighed grain inside a commencing. Rate, bag weight and pay-after come from the commencing."""

    __tablename__ = "purchase_entries"
    __table_args__ = (
        CheckConstraint("filled_bags >= 0", name="ck_entries_bags"),
        CheckConstraint("extra_kilos >= 0", name="ck_entries_kilos"),
        CheckConstraint("raw_weight IS NULL OR raw_weight >= 0", name="ck_entries_raw_weight"),
        CheckConstraint("borrowing >= 0", name="ck_entries_borrowing"),
        CheckConstraint("borrowing <= payable_amount", name="ck_entries_borrowing_le_payable"),
        Index("ix_entries_farmer", "farmer_id"),
        Index("ix_entries_commencing", "commencing_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    commencing_id: Mapped[int] = mapped_column(ForeignKey("commencings.id"))
    farmer_id: Mapped[int] = mapped_column(ForeignKey("farmers.id"))
    labour_group_id: Mapped[int] = mapped_column(ForeignKey("labour_groups.id"))
    entry_date: Mapped[date] = mapped_column(Date)
    filled_bags: Mapped[int] = mapped_column(Integer)
    extra_kilos: Mapped[int] = mapped_column(Integer, default=0)  # loose kg on top of the full bags
    raw_weight: Mapped[int | None] = mapped_column(Integer)  # reference only, never used in payment
    payable_amount: Mapped[int] = mapped_column(BigInteger)  # ceil(((bags*net + kilos)/20) * rate)
    borrowing: Mapped[int] = mapped_column(BigInteger, default=0)  # advance taken by the farmer, deducted
    due_date: Mapped[date] = mapped_column(Date)  # entry_date + pay_after_days
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    commencing: Mapped[Commencing] = relationship(lazy="joined")
    farmer: Mapped[Farmer] = relationship(lazy="joined")
    labour_group: Mapped[LabourGroup] = relationship(lazy="joined")

    @property
    def net_payable(self) -> int:
        return self.payable_amount - self.borrowing


class Payment(TimestampMixin, Base):
    """Every rupee paid out, with who received it. Allocations say which entries it settled."""

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(
            "party_type IN ('farmer', 'transporter', 'labour', 'bag_supplier', 'broker')", name="ck_payments_party_type"
        ),
        CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        CheckConstraint("method IN ('cash', 'cheque', 'upi', 'bank')", name="ck_payments_method"),
        CheckConstraint("receiver_mobile ~ '^[0-9]{10}$'", name="ck_payments_receiver_mobile"),
        Index("ix_payments_party", "party_type", "party_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    party_type: Mapped[str] = mapped_column(String(20))
    party_id: Mapped[int] = mapped_column(Integer)
    amount: Mapped[int] = mapped_column(BigInteger)
    payment_date: Mapped[date] = mapped_column(Date)
    business_year: Mapped[str] = mapped_column(String(7), index=True)
    method: Mapped[str] = mapped_column(String(10))
    receiver_name: Mapped[str] = mapped_column(String(200))
    receiver_mobile: Mapped[str] = mapped_column(String(10))
    reference_no: Mapped[str | None] = mapped_column(String(60))  # cheque / UPI reference
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    allocations: Mapped[list["PaymentAllocation"]] = relationship(lazy="selectin", order_by="PaymentAllocation.id")


class PaymentAllocation(Base):
    __tablename__ = "payment_allocations"
    __table_args__ = (
        CheckConstraint(
            "payable_type IN ('purchase_entry', 'truck_trip', 'labour_work', 'bag_supply', 'bilty_brokerage')",
            name="ck_alloc_payable_type",
        ),
        CheckConstraint("amount > 0", name="ck_alloc_amount_positive"),
        Index("ix_alloc_payable", "payable_type", "payable_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"))
    payable_type: Mapped[str] = mapped_column(String(20), default="purchase_entry")
    payable_id: Mapped[int] = mapped_column(Integer)
    amount: Mapped[int] = mapped_column(BigInteger)


class AuditLog(Base):
    """Who changed what and when. Rows are only ever inserted."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    username: Mapped[str] = mapped_column(String(30))
    action: Mapped[str] = mapped_column(String(15))
    table_name: Mapped[str] = mapped_column(String(30))
    record_id: Mapped[int | None] = mapped_column(Integer)
    changes: Mapped[dict | None] = mapped_column(JSONB)
