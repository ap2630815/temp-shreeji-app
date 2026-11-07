from contextvars import ContextVar
from datetime import date

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


class YearLockedError(Exception):
    """The date is outside the years this user may write to (reason 'closed'), or the user may not change existing entries (reason 'no_edit')."""

    def __init__(self, label: str, reason: str = "closed"):
        self.label = label
        self.reason = reason
        super().__init__(f"Business year {label}: {reason}")


# ---- standard business-year rules -------------------------------------------------------------------------------
# Business year = Oct-Sep. Who may write where:
#   owner       adds AND edits entries in the current year and the 2 before it (the last OWNER_YEARS years)
#   accountant  only ADDS entries, only in the current year; never edits an existing entry
# Everything else is read-only. All checks below go through these helpers; never compare years by hand.
OWNER_YEARS = 3

# the signed-in user's role for this request (set by deps.current_user); defaults to the most restrictive
_actor_role: ContextVar[str] = ContextVar("actor_role", default="accountant")


def set_actor(user) -> None:
    _actor_role.set(user.role)


def business_year_of(d: date) -> str:
    """Business year runs October to September: 2025-10-01 .. 2026-09-30 is '2025-26'."""
    start = d.year if d.month >= 10 else d.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def year_bounds(label: str) -> tuple[date, date]:
    start = int(label[:4])
    return date(start, 10, 1), date(start + 1, 9, 30)


def current_year_label() -> str:
    return business_year_of(date.today())


def writable_years(role: str) -> list[str]:
    """Years that accept new entries for this role, newest first."""
    start = int(current_year_label()[:4])
    n = OWNER_YEARS if role == "owner" else 1
    return [f"{y}-{(y + 1) % 100:02d}" for y in range(start, start - n, -1)]


def can_edit_year(user, label: str) -> bool:
    """May this user change an existing entry of business year `label`? (Only the owner, within the last 3 years.)"""
    return user.role == "owner" and label in writable_years("owner")


def year_is_locked(user, label: str) -> bool:
    """True when this user cannot write to year `label` at all (used for the 'Closed' badge)."""
    return label not in writable_years(user.role)


async def assert_year_open(db: AsyncSession, d: date) -> str:
    """ADDING an entry dated `d`: allowed in the writable years of the current user's role. `db` is unused (kept for call sites)."""
    label = business_year_of(d)
    if label not in writable_years(_actor_role.get()):
        raise YearLockedError(label, "closed")
    return label


async def assert_year_editable(db: AsyncSession, d: date) -> str:
    """CHANGING or deleting an existing entry dated `d`: owner only, and only in the last 3 years."""
    label = business_year_of(d)
    if _actor_role.get() != "owner":
        raise YearLockedError(label, "no_edit")
    if label not in writable_years("owner"):
        raise YearLockedError(label, "closed")
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
