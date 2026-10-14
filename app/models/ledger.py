"""Ledger tables (file5-payment-ledger.txt): money paid out / received and how it was allocated."""

from datetime import date

from sqlalchemy import BigInteger, CheckConstraint, Date, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.masters import Industry
from app.models.transactions import BUSINESS_YEAR


class Payment(TimestampMixin, Base):
    """Every rupee paid out, with who received it. party_type picks the table party_id points to:
    farmer -> farmers, truck -> trucks (paid to the truck owner), labour_group -> labour_groups,
    bag_supplier -> bag_suppliers, broker -> brokers."""

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        CheckConstraint("method IN ('cash', 'cheque', 'upi', 'bank')", name="ck_payments_method"),
        CheckConstraint("receiver_mobile ~ '^[0-9]{10}$'", name="ck_payments_receiver_mobile"),
        CheckConstraint("party_type IN ('farmer', 'truck', 'labour_group', 'bag_supplier', 'broker')", name="ck_payments_party_type"),
        CheckConstraint("status IN ('partial', 'final', 'complete')", name="ck_payments_status"),
        CheckConstraint(f"business_year ~ '{BUSINESS_YEAR}'", name="ck_payments_business_year_format"),
        Index("ix_payments_business_year", "business_year"),
        Index("ix_payments_party", "party_type", "party_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    party_type: Mapped[str] = mapped_column(String(20))
    party_id: Mapped[int] = mapped_column(Integer)
    amount: Mapped[int] = mapped_column(BigInteger)
    payment_date: Mapped[date] = mapped_column(Date)
    business_year: Mapped[str] = mapped_column(String(7))
    method: Mapped[str] = mapped_column(String(10))
    receiver_name: Mapped[str] = mapped_column(String(120))
    receiver_mobile: Mapped[str] = mapped_column(String(10))
    reference_no: Mapped[str | None] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(10))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    allocations: Mapped[list["PaymentAllocation"]] = relationship(lazy="selectin", order_by="PaymentAllocation.id")


class PaymentAllocation(Base):
    __tablename__ = "payment_allocations"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_alloc_amount_positive"),
        CheckConstraint("payable_type IN ('farmer', 'truck', 'labour_group', 'bag_supplier', 'broker')", name="ck_alloc_payable_type"),
        Index("ix_alloc_payable", "payable_type", "payable_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payments.id"))
    payable_type: Mapped[str] = mapped_column(String(15), default="farmer", server_default="farmer")
    payable_id: Mapped[int] = mapped_column(Integer)
    amount: Mapped[int] = mapped_column(BigInteger)


class Receipt(TimestampMixin, Base):
    """Money received from an industry; allocations say which bilties it settled."""

    __tablename__ = "receipts"
    __table_args__ = (
        CheckConstraint("method IN ('cash', 'cheque', 'upi', 'bank')", name="ck_receipts_method"),
        CheckConstraint("amount > 0", name="ck_receipts_amount"),
        CheckConstraint(f"business_year ~ '{BUSINESS_YEAR}'", name="ck_receipts_business_year_format"),
        Index("ix_receipts_business_year", "business_year"),
        Index("ix_receipts_industry_id", "industry_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    industry_id: Mapped[int] = mapped_column(ForeignKey("industries.id"))
    amount: Mapped[int] = mapped_column(BigInteger)
    receipt_date: Mapped[date] = mapped_column(Date)
    business_year: Mapped[str] = mapped_column(String(7))
    method: Mapped[str] = mapped_column(String(10))
    reference_no: Mapped[str | None] = mapped_column(String(60))
    payer_name: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))

    industry: Mapped[Industry] = relationship(lazy="joined")
    allocations: Mapped[list["ReceiptAllocation"]] = relationship(lazy="selectin", order_by="ReceiptAllocation.id")


class ReceiptAllocation(Base):
    __tablename__ = "receipt_allocations"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_receipt_alloc_amount"),
        Index("ix_receipt_alloc_bilty", "bilty_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("receipts.id"))
    bilty_id: Mapped[int] = mapped_column(ForeignKey("bilties.id"))
    amount: Mapped[int] = mapped_column(BigInteger)
