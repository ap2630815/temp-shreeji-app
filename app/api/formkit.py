"""Small helpers shared by the hand-written (non-generic) form screens."""

from dataclasses import replace
from datetime import date
from typing import Any

from fastapi import Request

from app.api.masters_config import F
from app.services.years import current_year_label


def today() -> date:
    return date.today()


async def read_form(request: Request) -> dict[str, str]:
    return {k: v for k, v in (await request.form()).items() if isinstance(v, str)}


def normalize_fields(fields: list[F], raw: dict[str, str]) -> dict[str, Any]:
    """Strip, blank -> None, ints parsed where the field is numeric (left as text on failure so validation reports it)."""
    out: dict[str, Any] = {}
    for f in fields:
        value = (raw.get(f.name) or "").strip()
        if value == "":
            out[f.name] = None
            continue
        if f.kind in ("int", "choice"):
            try:
                value = int(value)
            except ValueError:
                pass
        out[f.name] = value
    return out


def lock(fields: list[F], names: set[str]) -> list[F]:
    return [replace(f, locked=True) if f.name in names else f for f in fields]


def form_context(*, fields: list[F], values: dict, errors: dict, action: str, heading: tuple[str, str], back_url: str, **extra) -> dict:
    return dict(fields=fields, values=values, errors=errors, action=action, heading=heading, back_url=back_url, **extra)


GENERIC_ERROR = ("Could not save, please check the values", "સાચવી શકાયું નહીં, કૃપા કરીને કિંમતો તપાસો")
YEAR_LOCKED = lambda label: (  # noqa: E731
    f"Date is in business year {label}, which is closed. Use a date in {current_year_label()} (Oct-Sep)",
    f"તારીખ વ્યવસાય વર્ષ {label} માં છે, જે બંધ છે. {current_year_label()} (ઓક્ટો-સપ્ટે) ની તારીખ વાપરો",
)
