import zlib

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def advisory_lock(db: AsyncSession, kind: str, record_id: int) -> None:
    """Transaction-scoped lock on (kind, id): serialises writers that must read-then-write the same figures
    (stock being loaded, money being allocated). Released automatically at commit/rollback."""
    key = (zlib.crc32(kind.encode()) % 1_000_000) * 1_000_000_000 + record_id
    await db.execute(select(func.pg_advisory_xact_lock(key)))
