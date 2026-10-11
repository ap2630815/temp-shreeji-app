from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BusinessYear


class YearLockedError(Exception):
    def __init__(self, label: str):
        self.label = label
        super().__init__(f"Business year {label} is locked")


def business_year_of(d: date) -> str:
    """Business year runs October to September: 2025-10-01 .. 2026-09-30 is '2025-26'."""
    start = d.year if d.month >= 10 else d.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def year_bounds(label: str) -> tuple[date, date]:
    start = int(label[:4])
    return date(start, 10, 1), date(start + 1, 9, 30)


async def assert_year_open(db: AsyncSession, d: date) -> str:
    label = business_year_of(d)
    row = await db.get(BusinessYear, label)
    if row is not None and row.is_locked:
        raise YearLockedError(label)
    return label
