from datetime import date

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


class YearLockedError(Exception):
    """The date is outside the current business year, so the year is closed for new or changed entries."""

    def __init__(self, label: str):
        self.label = label
        super().__init__(f"Business year {label} is closed")


def business_year_of(d: date) -> str:
    """Business year runs October to September: 2025-10-01 .. 2026-09-30 is '2025-26'."""
    start = d.year if d.month >= 10 else d.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def year_bounds(label: str) -> tuple[date, date]:
    start = int(label[:4])
    return date(start, 10, 1), date(start + 1, 9, 30)


def current_year_label() -> str:
    return business_year_of(date.today())


async def assert_year_open(db: AsyncSession, d: date) -> str:
    """Only the current business year accepts entries; every earlier year is closed automatically on 1 October.
    `db` is unused (kept so call sites stay unchanged)."""
    label = business_year_of(d)
    if label != current_year_label():
        raise YearLockedError(label)
    return label


def allowed_years(user, found) -> list[str]:
    """Years a user may browse, newest first: the owner sees every year with data, others only the current one."""
    current = current_year_label()
    if user.role == "owner":
        return sorted({current, *found}, reverse=True)
    return [current]


def require_year_visible(user, label: str) -> None:
    if user.role != "owner" and label != current_year_label():
        raise HTTPException(403, detail="Only the owner can view past business years")
