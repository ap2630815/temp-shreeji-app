"""Where grain is stored: the distinct locations written so far, offered as a drop-down on the farmer entry forms."""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PurchaseFarmerEntry, PurchaseIndividual

_PARENTHESES = re.compile(r"\([^)]*\)")


def location_key(text: str | None) -> str:
    """'Godown (behind the shop)' -> 'Godown': anything in parentheses is ignored when comparing locations."""
    return " ".join(_PARENTHESES.sub(" ", text or "").split())


async def stored_locations(db: AsyncSession) -> tuple[tuple[str, str], ...]:
    """(value, label) pairs, one per distinct location (case-insensitive, parentheses ignored), sorted."""
    seen: dict[str, str] = {}
    for model in (PurchaseFarmerEntry, PurchaseIndividual):
        for text in (await db.scalars(select(model.grain_stored_location).where(model.grain_stored_location.is_not(None)).distinct())).all():
            key = location_key(text)
            if key:
                seen.setdefault(key.casefold(), key)
    return tuple((v, v) for v in sorted(seen.values(), key=str.casefold))
