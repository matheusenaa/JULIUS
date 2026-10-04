"""Protocolo de sincronização (lado servidor) e serialização compartilhada.

PULL  GET  /api/sync/pull?since=<cursor>  → linhas alteradas desde o cursor (inclui excluídas)
PUSH  POST /api/sync/push                 → [{entity, id, base_version, data}]
       - registro novo           → inserido (o id UUID vem do dispositivo)
       - base_version == versão  → aplicado; versão sobe
       - base_version != versão  → CONFLITO: devolve a versão do servidor; nada é sobrescrito

Regras de negócio continuam valendo: constraints do banco, posse de cada referência
(conta/categoria/etc. precisam ser do mesmo usuário) e fatura do cartão recalculada.
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Account,
    Budget,
    Category,
    Debt,
    Goal,
    InstallmentPlan,
    Recurrence,
    Transaction,
    User,
)
from app.models.base import utcnow
from app.services.backup import _coerce
from app.services.cards import invoice_month_for

# Ordem respeita as chaves estrangeiras
ENTITIES: list[tuple[str, type]] = [
    ("accounts", Account),
    ("categories", Category),
    ("recurrences", Recurrence),
    ("installment_plans", InstallmentPlan),
    ("debts", Debt),
    ("transactions", Transaction),
    ("budgets", Budget),
    ("goals", Goal),
]
MODEL_BY_NAME = dict(ENTITIES)
NOT_SYNCED = {"user_id", "synced_version"}
# Colunas que apontam para outros registros do usuário (verificação de posse)
REFS = {
    "account_id": Account,
    "to_account_id": Account,
    "category_id": Category,
    "parent_id": Category,
    "recurrence_id": Recurrence,
    "installment_plan_id": InstallmentPlan,
    "debt_id": Debt,
}
PULL_LIMIT = 5000


def columns(model) -> dict:
    return {c.key: c for c in model.__table__.columns if c.key not in NOT_SYNCED}


def serialize(obj) -> dict:
    out = {}
    for key in columns(type(obj)):
        v = getattr(obj, key)
        out[key] = v.isoformat() if isinstance(v, date | datetime) else v
    return out


def _naive_utc(dt: datetime) -> datetime:
    return (dt.astimezone(UTC) if dt.tzinfo else dt).replace(tzinfo=None)


def _since_param(db: Session, since: datetime) -> datetime:
    # SQLite grava datas sem fuso (em UTC); Postgres compara com fuso
    return _naive_utc(since) if db.bind.dialect.name == "sqlite" else since.astimezone(UTC)


def pull(db: Session, user: User, since: datetime | None) -> dict:
    server_time = utcnow()
    changes: dict[str, list[dict]] = {}
    has_more = False
    for name, model in ENTITIES:
        q = select(model).where(model.user_id == user.id)
        if since is not None:
            q = q.where(model.updated_at >= _since_param(db, since - timedelta(seconds=2)))
        if name == "categories":
            q = q.order_by(model.parent_id.is_not(None), model.updated_at)
        else:
            q = q.order_by(model.updated_at)
        rows = db.scalars(q.limit(PULL_LIMIT + 1)).all()
        has_more = has_more or len(rows) > PULL_LIMIT
        changes[name] = [serialize(r) for r in rows[:PULL_LIMIT]]
    return {"server_time": server_time.isoformat(), "changes": changes, "has_more": has_more}


def apply_fields(obj, model, data: dict) -> None:
    cols = columns(model)
    for key, value in data.items():
        if key in cols and key not in ("id", "version", "created_at", "updated_at"):
            setattr(obj, key, _coerce(cols[key], value))


def _check_refs(db: Session, user_id: str, data: dict) -> str | None:
    for key, ref_model in REFS.items():
        ref_id = data.get(key)
        if ref_id:
            ref = db.get(ref_model, ref_id)
            if ref is None or ref.user_id != user_id:
                return f"{key} aponta para um registro inexistente ou de outro usuário"
    return None


def _fix_business(db: Session, obj) -> None:
    if isinstance(obj, Transaction) and obj.type in ("income", "expense") and obj.installment_plan_id is None:
        acc = db.get(Account, obj.account_id)
        obj.invoice_month = (
            invoice_month_for(obj.occurred_on, acc.closing_day) if acc and acc.kind == "credit_card" else None
        )


def push(db: Session, user: User, changes: list[dict]) -> list[dict]:
    order = {name: i for i, (name, _) in enumerate(ENTITIES)}
    results = []
    for ch in sorted(changes, key=lambda c: order.get(c.get("entity"), 99)):
        entity, obj_id = ch.get("entity"), ch.get("id")
        model = MODEL_BY_NAME.get(entity)
        data = ch.get("data") or {}
        base = {"entity": entity, "id": obj_id}
        if model is None or not isinstance(obj_id, str) or len(obj_id) != 36:
            results.append({**base, "status": "rejected", "error": "Entidade ou id inválido"})
            continue
        problem = _check_refs(db, user.id, data)
        if problem:
            results.append({**base, "status": "rejected", "error": problem})
            continue
        row = db.get(model, obj_id)
        if row is not None and row.user_id != user.id:
            results.append({**base, "status": "rejected", "error": "Identificador em uso"})
            continue
        if row is not None and ch.get("base_version") != row.version:
            results.append({**base, "status": "conflict", "server": serialize(row)})
            continue
        try:
            with db.begin_nested():
                if row is None:
                    row = model(id=obj_id, user_id=user.id)
                    apply_fields(row, model, data)
                    row.version = max(1, int(data.get("version") or 1))
                    _fix_business(db, row)
                    db.add(row)
                else:
                    apply_fields(row, model, data)
                    _fix_business(db, row)
                db.flush()
            results.append({**base, "status": "applied", "version": row.version})
        except (IntegrityError, ValueError, TypeError) as exc:
            results.append({**base, "status": "rejected", "error": f"Dados inválidos: {type(exc).__name__}"})
    db.commit()
    return results
