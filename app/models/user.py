from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class User(TimestampMixin, Base):
    """Only two roles may log in: the business owner (max 1) and the accountant (max 2).

    Owner limit: partial unique index. Accountant limit: DB trigger `trg_users_max_accountants`
    (see migration a1c0de5e7b21), since an index cannot cap a count at 2.
    """

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('owner', 'accountant')", name="ck_users_role"),
        Index("uq_users_single_owner", "role", unique=True, postgresql_where=text("role = 'owner'")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(30), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(15))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


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
