"""Exportação (CSV / JSON) e restauração de backup.

A restauração só INSERE registros que ainda não existem (pelo id). Nunca apaga
nem sobrescreve nada — restaurar duas vezes o mesmo arquivo é inofensivo.
"""

import csv
import io
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import BadRequest
from app.models import (
    Account,
    Budget,
    CategorizationRule,
    Category,
    Goal,
    InstallmentPlan,
    Recurrence,
    Transaction,
    User,
)
from app.models.base import utcnow
from app.services import audit

BACKUP_VERSION = 1
# Ordem respeita as chaves estrangeiras
MODELS = [
    ("accounts", Account),
    ("categories", Category),
    ("recurrences", Recurrence),
    ("installment_plans", InstallmentPlan),
    ("transactions", Transaction),
    ("budgets", Budget),
    ("goals", Goal),
    ("categorization_rules", CategorizationRule),
]

TYPE_PT = {"income": "Receita", "expense": "Despesa", "transfer": "Transferência"}
STATUS_PT = {"paid": "Realizado", "pending": "Previsto"}
PAYMENT_PT = {
    "pix": "Pix",
    "debit": "Débito",
    "credit": "Crédito",
    "cash": "Dinheiro",
    "boleto": "Boleto",
    "transfer": "Transferência",
    "other": "Outro",
}


def _plain(v):
    return v.isoformat() if isinstance(v, date | datetime) else v


def _row(obj) -> dict:
    return {c.key: _plain(getattr(obj, c.key)) for c in obj.__table__.columns if c.key != "user_id"}


def export_json(db: Session, user: User) -> dict:
    data = {
        "app": "JULIUS",
        "version": BACKUP_VERSION,
        "exported_at": utcnow().isoformat(),
        "user": {"email": user.email, "name": user.name, "settings": user.settings},
    }
    for key, model in MODELS:
        q = select(model).where(model.user_id == user.id)
        if key == "categories":
            q = q.order_by(Category.parent_id.is_not(None))  # principais antes das subcategorias
        data[key] = [_row(o) for o in db.scalars(q)]
    return data


def _safe_cell(value) -> str:
    """Evita injeção de fórmula ao abrir o CSV no Excel."""
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def export_csv(db: Session, user_id: str) -> str:
    cats = {c.id: c for c in db.scalars(select(Category).where(Category.user_id == user_id))}
    accs = {a.id: a.name for a in db.scalars(select(Account).where(Account.user_id == user_id))}
    out = io.StringIO()
    out.write("﻿")  # BOM: Excel reconhece UTF-8 (acentos)
    w = csv.writer(out, delimiter=";")
    w.writerow(
        [
            "Data",
            "Tipo",
            "Descrição",
            "Categoria",
            "Subcategoria",
            "Conta",
            "Conta destino",
            "Valor",
            "Situação",
            "Forma de pagamento",
            "Fixa",
            "Observações",
        ]
    )
    for t in db.scalars(
        select(Transaction)
        .where(Transaction.user_id == user_id, Transaction.deleted_at.is_(None))
        .order_by(Transaction.occurred_on, Transaction.created_at)
    ):
        cat = cats.get(t.category_id)
        parent = cats.get(cat.parent_id) if cat and cat.parent_id else None
        w.writerow(
            [
                t.occurred_on.strftime("%d/%m/%Y"),
                TYPE_PT[t.type],
                _safe_cell(t.description),
                _safe_cell(parent.name if parent else (cat.name if cat else "")),
                _safe_cell(cat.name if parent else ""),
                _safe_cell(accs.get(t.account_id, "")),
                _safe_cell(accs.get(t.to_account_id, "")),
                f"{t.amount_cents / 100:.2f}".replace(".", ","),
                STATUS_PT[t.status],
                PAYMENT_PT.get(t.payment_method, ""),
                "Sim" if t.is_fixed else "Não",
                _safe_cell(t.notes),
            ]
        )
    return out.getvalue()


def _coerce(column, value):
    if value is None:
        return None
    try:
        py = column.type.python_type
    except NotImplementedError:
        return value
    if py is date and isinstance(value, str):
        return date.fromisoformat(value[:10])
    if py is datetime and isinstance(value, str):
        return datetime.fromisoformat(value)
    return value


def restore_json(db: Session, user: User, payload: dict) -> dict:
    if payload.get("app") != "JULIUS" or payload.get("version") != BACKUP_VERSION:
        raise BadRequest("Arquivo de backup inválido ou de versão incompatível.")
    summary = {}
    try:
        for key, model in MODELS:
            rows = payload.get(key) or []
            if not isinstance(rows, list):
                raise BadRequest(f'Seção "{key}" inválida no backup.')
            cols = {c.key: c for c in model.__table__.columns if c.key != "user_id"}
            inserted = 0
            for row in rows:
                if not isinstance(row, dict) or not row.get("id") or db.get(model, row["id"]):
                    continue
                values = {k: _coerce(cols[k], v) for k, v in row.items() if k in cols}
                db.add(model(user_id=user.id, **values))
                inserted += 1
            db.flush()
            summary[key] = inserted
    except IntegrityError as exc:
        db.rollback()
        raise BadRequest(
            "O backup contém dados inconsistentes e não foi restaurado. Nada foi alterado."
        ) from exc
    except (TypeError, ValueError) as exc:
        db.rollback()
        raise BadRequest("O backup contém campos em formato inválido. Nada foi alterado.") from exc
    audit.record(
        db,
        user.id,
        "backup",
        None,
        "restore",
        f"Backup restaurado: {summary.get('transactions', 0)} lançamento(s) adicionados.",
        summary,
    )
    db.commit()
    return summary
