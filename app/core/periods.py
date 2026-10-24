"""The toolbar's date filter: a preset period ending today (`period=d3|w1|...`) or one specific day (`period=date&on_date=YYYY-MM-DD`)."""

import calendar
from collections.abc import Mapping
from datetime import date, timedelta

# key, English, Gujarati, (unit, count)
PERIODS: tuple[tuple[str, str, str, tuple[str, int]], ...] = (
    ("d3", "Last 3 days", "છેલ્લા ૩ દિવસ", ("d", 3)),
    ("w1", "Last 1 week", "છેલ્લું ૧ અઠવાડિયું", ("d", 7)),
    ("w2", "Last 2 weeks", "છેલ્લા ૨ અઠવાડિયા", ("d", 14)),
    ("w3", "Last 3 weeks", "છેલ્લા ૩ અઠવાડિયા", ("d", 21)),
    ("m1", "Last 1 month", "છેલ્લો ૧ મહિનો", ("m", 1)),
    ("m2", "Last 2 months", "છેલ્લા ૨ મહિના", ("m", 2)),
    ("q1", "Last 1 quarter", "છેલ્લું ૧ ત્રિમાસિક", ("m", 3)),
    ("q2", "Last 2 quarters", "છેલ્લા ૨ ત્રિમાસિક", ("m", 6)),
)
PERIOD_KEYS = {p[0]: p for p in PERIODS}


def _months_back(d: date, n: int) -> date:
    month = d.month - n
    year = d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def date_window(params: Mapping[str, str], today: date) -> tuple[date, date] | None:
    """(first, last) day to show, both inclusive, or None when the date filter is off."""
    period = (params.get("period") or "").strip()
    if period == "date":
        try:
            d = date.fromisoformat((params.get("on_date") or "").strip())
        except ValueError:
            return None
        return d, d
    spec = PERIOD_KEYS.get(period)
    if spec is None:
        return None
    unit, n = spec[3]
    return (today - timedelta(days=n - 1) if unit == "d" else _months_back(today, n)), today
