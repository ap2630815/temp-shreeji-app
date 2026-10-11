from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, User


def _plain(v: Any) -> Any:
    return v.isoformat() if isinstance(v, date) else v


def diff(before: dict[str, Any] | None, after: dict[str, Any]) -> dict[str, Any]:
    """For create: all values. For update: only changed fields as {field: [old, new]}."""
    if before is None:
        return {k: _plain(v) for k, v in after.items()}
    return {k: [_plain(before.get(k)), _plain(v)] for k, v in after.items() if before.get(k) != v}


def log(db: AsyncSession, user: User, action: str, table: str, record_id: int | None, changes: dict | None) -> None:
    db.add(AuditLog(user_id=user.id, username=user.username, action=action, table_name=table, record_id=record_id, changes=changes))
