from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog


def _plain(value: Any) -> Any:
    if isinstance(value, date | datetime):
        return value.isoformat()
    return value


def diff(before: dict, after: dict) -> dict:
    """Campos alterados: {campo: [antes, depois]}."""
    return {k: [_plain(before.get(k)), _plain(after.get(k))] for k in after if before.get(k) != after.get(k)}


def record(
    db: Session,
    user_id: str | None,
    entity: str,
    entity_id: str | None,
    action: str,
    summary: str,
    changes: dict | None = None,
    ip: str | None = None,
) -> None:
    """Adiciona ao histórico na mesma transação da alteração (atômico com ela)."""
    db.add(
        AuditLog(
            user_id=user_id,
            entity=entity,
            entity_id=entity_id,
            action=action,
            summary=summary[:300],
            changes={k: _plain(v) for k, v in changes.items()} if changes else None,
            ip=ip,
        )
    )
