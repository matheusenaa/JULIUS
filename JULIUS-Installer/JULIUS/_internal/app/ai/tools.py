"""Ferramentas que a IA pode usar — e só elas.

Leitura: executam na hora, sempre filtradas pelo usuário logado.
Escrita/exclusão: NUNCA executam direto. Viram uma AIAction "pending" que o
usuário confirma na interface; a execução usa os mesmos serviços e validações da API.
"""

import json
from datetime import date, timedelta

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, AIAction, Category, Recurrence, Transaction, User
from app.models.base import utcnow
from app.schemas import RecurrenceIn, TransactionIn, TransactionUpdate
from app.services import analytics, audit, ledger
from app.services import debts as debts_svc
from app.services import forecast as fc
from app.services import transactions as tx_svc
from app.services.categorizer import normalize
from app.services.dates import month_end, month_start
from app.services.money import brl
from app.services.ownership import get_owned

MAX_ROWS = 20

_period = {
    "start": {"type": "string", "description": "Data inicial AAAA-MM-DD (opcional)"},
    "end": {"type": "string", "description": "Data final AAAA-MM-DD (opcional)"},
}

SPECS: list[dict] = [
    {
        "name": "get_balance",
        "description": "Saldo disponível hoje e saldo de cada conta/cartão.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_transactions",
        "description": "Lista lançamentos (máx. 20) com filtros.",
        "parameters": {
            "type": "object",
            "properties": {
                **_period,
                "type": {"type": "string", "enum": ["income", "expense", "transfer"]},
                "category": {"type": "string", "description": "Nome da categoria"},
                "search": {"type": "string", "description": "Texto na descrição"},
                "amount": {"type": "number", "description": "Valor exato em reais"},
            },
        },
    },
    {
        "name": "get_future_expenses",
        "description": "Compromissos futuros (contas, salário, faturas, parcelas) com saldo projetado após cada um.",
        "parameters": {
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 180}},
        },
    },
    {
        "name": "get_income",
        "description": "Receitas realizadas no período, por categoria.",
        "parameters": {"type": "object", "properties": _period},
    },
    {
        "name": "get_spending_by_category",
        "description": "Despesas realizadas no período, por categoria.",
        "parameters": {"type": "object", "properties": _period},
    },
    {
        "name": "compare_with_last_month",
        "description": "Compara gastos do mês até hoje com o mesmo período do mês passado, por categoria.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_categories",
        "description": "Categorias do usuário.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_debts",
        "description": "Dívidas com valor restante e próximo vencimento (calculados).",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_goals",
        "description": "Metas financeiras e progresso.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "create_transaction",
        "description": "PROPÕE um novo lançamento (o usuário precisa confirmar).",
        "parameters": {
            "type": "object",
            "required": ["type", "amount", "description"],
            "properties": {
                "type": {"type": "string", "enum": ["income", "expense"]},
                "amount": {"type": "number", "description": "Valor em reais, ex.: 45.9"},
                "description": {"type": "string"},
                "date": {"type": "string", "description": "AAAA-MM-DD; padrão hoje"},
                "category": {"type": "string"},
                "account": {"type": "string"},
                "status": {"type": "string", "enum": ["paid", "pending", "confirmed"]},
            },
        },
    },
    {
        "name": "update_transaction",
        "description": "PROPÕE alterar um lançamento existente (precisa de confirmação).",
        "parameters": {
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "string"},
                "amount": {"type": "number"},
                "description": {"type": "string"},
                "date": {"type": "string"},
                "category": {"type": "string"},
                "status": {"type": "string", "enum": ["paid", "pending", "confirmed", "canceled"]},
            },
        },
    },
    {
        "name": "delete_transaction",
        "description": "PROPÕE excluir um lançamento (precisa de confirmação).",
        "parameters": {"type": "object", "required": ["id"], "properties": {"id": {"type": "string"}}},
    },
    {
        "name": "create_future_expense",
        "description": "PROPÕE uma conta futura ou recorrente (aluguel, internet, salário...). Precisa de confirmação.",
        "parameters": {
            "type": "object",
            "required": ["type", "amount", "description", "date"],
            "properties": {
                "type": {"type": "string", "enum": ["income", "expense"]},
                "amount": {"type": "number"},
                "description": {"type": "string"},
                "date": {"type": "string", "description": "Primeiro vencimento AAAA-MM-DD"},
                "category": {"type": "string"},
                "account": {"type": "string"},
                "monthly": {"type": "boolean", "description": "Repete todo mês"},
            },
        },
    },
]
WRITE_TOOLS = {"create_transaction", "update_transaction", "delete_transaction", "create_future_expense"}


class ToolError(Exception):
    pass


def _date(value, default: date | None = None) -> date | None:
    if not value:
        return default
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise ToolError(f"Data inválida: {value}") from exc


def _cents(value) -> int:
    if not isinstance(value, int | float) or value <= 0 or value > 10**10:
        raise ToolError("Valor inválido.")
    return round(float(value) * 100)  # conversão de unidade (reais → centavos), não cálculo


def _category(db: Session, user: User, name: str | None, kind: str | None = None) -> str | None:
    if not name:
        return None
    target = normalize(name)
    cats = db.scalars(
        select(Category).where(Category.user_id == user.id, Category.deleted_at.is_(None))
    ).all()
    match = [c for c in cats if normalize(c.name) == target and (kind is None or c.kind == kind)]
    if not match:
        raise ToolError(f'Categoria "{name}" não existe. Use get_categories.')
    match.sort(key=lambda c: c.parent_id is None)
    return match[0].id


def _account(db: Session, user: User, name: str | None) -> str:
    accounts = db.scalars(
        select(Account)
        .where(Account.user_id == user.id, Account.deleted_at.is_(None))
        .order_by(Account.created_at)
    ).all()
    if name:
        for a in accounts:
            if normalize(a.name) == normalize(name):
                return a.id
        raise ToolError(f'Conta "{name}" não existe.')
    preferred = (user.settings or {}).get("default_account_id")
    for a in accounts:
        if a.id == preferred:
            return a.id
    non_cards = [a for a in accounts if a.kind != "credit_card"] or accounts
    if not non_cards:
        raise ToolError("Nenhuma conta cadastrada.")
    return non_cards[0].id


def _desc(user: User, tx: Transaction, cat_names: dict[str, str]) -> str:
    if (user.settings or {}).get("ai_share_descriptions") is False:
        return cat_names.get(tx.category_id or "", "Sem categoria")  # privacidade
    return tx.description


def _read(db: Session, user: User, name: str, args: dict, today: date) -> dict:
    uid = user.id
    start = _date(args.get("start"), month_start(today))
    end = _date(args.get("end"), today)
    if name == "get_balance":
        balances = ledger.account_balances(db, uid, as_of=today)
        accts = db.scalars(select(Account).where(Account.user_id == uid, Account.deleted_at.is_(None))).all()
        return {
            "available": brl(ledger.cash_balance(db, uid, today)),
            "accounts": [
                {"name": a.name, "kind": a.kind, "balance": brl(balances.get(a.id, 0))} for a in accts
            ],
        }
    if name == "get_transactions":
        cat_names = {c.id: c.name for c in db.scalars(select(Category).where(Category.user_id == uid))}
        filters = {"start": start, "end": end, "type": args.get("type"), "q": args.get("search")}
        if args.get("category"):
            filters["category_id"] = _category(db, user, args["category"])
        if args.get("amount"):
            filters["min_cents"] = filters["max_cents"] = _cents(args["amount"])
        page = tx_svc.list_filtered(db, uid, filters, 1, MAX_ROWS)
        return {
            "total_found": page["total"],
            "items": [
                {
                    "id": t.id,
                    "date": t.occurred_on.isoformat(),
                    "description": _desc(user, t, cat_names),
                    "amount": brl(t.amount_cents),
                    "type": t.type,
                    "status": t.status,
                    "category": cat_names.get(t.category_id or ""),
                }
                for t in page["items"]
            ],
        }
    if name == "get_future_expenses":
        days = max(1, min(int(args.get("days") or 30), 180))
        tl = fc.timeline(db, uid, today, today + timedelta(days=days))
        return {
            "current_balance": brl(tl["start_balance_cents"]),
            "projected_balance": brl(tl["end_balance_cents"]),
            "lowest_balance": {
                "date": tl["lowest"]["date"].isoformat(),
                "value": brl(tl["lowest"]["balance_cents"]),
            },
            "events": [
                {
                    "date": e.date.isoformat(),
                    "description": e.description,
                    "flow": e.flow,
                    "amount": brl(e.amount_cents),
                    "status": e.status,
                    "balance_after": brl(e.balance_after),
                }
                for e in tl["events"][:40]
            ],
        }
    if name in ("get_spending_by_category", "get_income"):
        if name == "get_income":
            totals = ledger.totals_by_type(db, uid, start, end)
            return {"period": [start.isoformat(), end.isoformat()], "income": brl(totals["income"])}
        cats = analytics.expenses_by_category(db, uid, start, end)
        return {
            "period": [start.isoformat(), end.isoformat()],
            "categories": [
                {"name": c["name"], "total": brl(c["total_cents"]), "share": f"{round(c['share'] * 100)}%"}
                for c in cats
            ],
        }
    if name == "compare_with_last_month":
        return compare_with_last_month(db, uid, today)
    if name == "get_categories":
        cats = db.scalars(
            select(Category).where(Category.user_id == uid, Category.deleted_at.is_(None))
        ).all()
        return {"categories": [{"name": c.name, "kind": c.kind} for c in cats]}
    if name == "get_debts":
        return {
            "debts": [
                {
                    "name": d.name,
                    "remaining": brl(s.remaining_cents),
                    "remaining_installments": s.remaining_installments,
                    "next_due": s.next_due.isoformat() if s.next_due else None,
                    "situation": s.situation,
                }
                for d, s in debts_svc.statuses(db, uid, today)
            ]
        }
    if name == "get_goals":
        return {
            "goals": [
                {"name": g["name"], "target": brl(g["target_cents"]), "progress": brl(g["progress_cents"])}
                for g in analytics.goals_status(db, uid, today)
            ]
        }
    raise ToolError(f"Ferramenta desconhecida: {name}")


def compare_with_last_month(db: Session, user_id: str, today: date) -> dict:
    start = month_start(today)
    prev_start = month_start(start - timedelta(days=1))
    prev_end = min(month_end(prev_start), prev_start + (today - start))
    now = {c["name"]: c["total_cents"] for c in analytics.expenses_by_category(db, user_id, start, today)}
    before = {
        c["name"]: c["total_cents"] for c in analytics.expenses_by_category(db, user_id, prev_start, prev_end)
    }
    rows = []
    for name in set(now) | set(before):
        diff = now.get(name, 0) - before.get(name, 0)
        rows.append(
            {
                "category": name,
                "this_month": now.get(name, 0),
                "last_month": before.get(name, 0),
                "diff": diff,
            }
        )
    rows.sort(key=lambda r: -r["diff"])
    return {
        "this_month_total": brl(sum(now.values())),
        "last_month_same_period_total": brl(sum(before.values())),
        "by_category": [
            {
                **r,
                "this_month": brl(r["this_month"]),
                "last_month": brl(r["last_month"]),
                "diff": brl(r["diff"]),
            }
            for r in rows
        ],
        "_raw": rows,
    }


def _propose(db: Session, user: User, name: str, args: dict, today: date) -> dict:
    """Valida e transforma a proposta da IA em payload exato da API. Não grava nada."""
    if name == "create_transaction":
        kind = args.get("type")
        payload = {
            "type": kind,
            "amount_cents": _cents(args.get("amount")),
            "description": str(args.get("description"))[:200],
            "occurred_on": _date(args.get("date"), today).isoformat(),
            "category_id": _category(db, user, args.get("category"), kind),
            "account_id": _account(db, user, args.get("account")),
            "status": args.get("status") or "paid",
            "source": "ai",
        }
        TransactionIn(**payload)
        summary = f"Registrar {'receita' if kind == 'income' else 'despesa'} de {brl(payload['amount_cents'])}: {payload['description']} ({payload['occurred_on']})."
    elif name in ("update_transaction", "delete_transaction"):
        tx = db.get(Transaction, str(args.get("id")))
        if tx is None or tx.user_id != user.id or tx.deleted_at is not None:
            raise ToolError("Lançamento não encontrado. Use get_transactions para obter o id.")
        if name == "delete_transaction":
            payload = {"id": tx.id}
            summary = f"Excluir {('receita' if tx.type == 'income' else 'despesa')} de {brl(tx.amount_cents)} — {tx.description} ({tx.occurred_on.strftime('%d/%m/%Y')})."
        else:
            changes: dict = {"version": tx.version}
            if args.get("amount") is not None:
                changes["amount_cents"] = _cents(args["amount"])
            if args.get("description"):
                changes["description"] = str(args["description"])[:200]
            if args.get("date"):
                changes["occurred_on"] = _date(args["date"]).isoformat()
            if args.get("category"):
                changes["category_id"] = _category(
                    db, user, args["category"], tx.type if tx.type != "transfer" else None
                )
            if args.get("status"):
                changes["status"] = args["status"]
            TransactionUpdate(**changes)
            payload = {"id": tx.id, "changes": changes}
            summary = (
                f'Alterar "{tx.description}" ({brl(tx.amount_cents)}): '
                + ", ".join(k for k in changes if k != "version")
                + "."
            )
    elif name == "create_future_expense":
        kind = args.get("type")
        first = _date(args.get("date"), today)
        base = {
            "type": kind,
            "amount_cents": _cents(args.get("amount")),
            "description": str(args.get("description"))[:200],
            "category_id": _category(db, user, args.get("category"), kind),
            "account_id": _account(db, user, args.get("account")),
        }
        if args.get("monthly"):
            payload = {
                "recurrence": {
                    **base,
                    "frequency": "monthly",
                    "day_of_month": first.day,
                    "start_date": first.isoformat(),
                    "is_fixed": True,
                }
            }
            RecurrenceIn(**payload["recurrence"])
            summary = f"Criar recorrência mensal: {base['description']} — {brl(base['amount_cents'])} todo dia {first.day}."
        else:
            payload = {
                "transaction": {**base, "occurred_on": first.isoformat(), "status": "pending", "source": "ai"}
            }
            TransactionIn(**payload["transaction"])
            summary = f"Agendar {base['description']} — {brl(base['amount_cents'])} em {first.strftime('%d/%m/%Y')}."
    else:
        raise ToolError(f"Ferramenta desconhecida: {name}")
    return {"payload": payload, "summary": summary}


def run_tool(
    db: Session, user: User, conversation_id: str | None, name: str, args: dict, today: date
) -> dict:
    """Executa uma chamada de ferramenta da IA. Erros voltam para a IA como texto, sem quebrar."""
    try:
        if name not in WRITE_TOOLS:
            result = _read(db, user, name, args or {}, today)
            result.pop("_raw", None)
            return result
        proposal = _propose(db, user, name, args or {}, today)
    except (ToolError, ValidationError, ValueError) as exc:
        msg = exc.errors()[0]["msg"] if isinstance(exc, ValidationError) else str(exc)
        return {"error": msg}
    action = AIAction(user_id=user.id, conversation_id=conversation_id, tool=name, **proposal)
    db.add(action)
    db.flush()
    return {
        "requires_user_confirmation": True,
        "action_id": action.id,
        "summary": proposal["summary"],
        "note": "Nada foi alterado ainda. Diga ao usuário para confirmar no botão.",
    }


def create_action(
    db: Session, user: User, conversation_id: str | None, name: str, payload: dict, summary: str
) -> AIAction:
    action = AIAction(
        user_id=user.id, conversation_id=conversation_id, tool=name, payload=payload, summary=summary
    )
    db.add(action)
    db.flush()
    return action


def execute_action(db: Session, user: User, action: AIAction) -> dict:
    """Executa uma ação JÁ CONFIRMADA pelo usuário, pelos mesmos serviços da API."""
    p = action.payload
    if action.tool == "create_transaction":
        tx = tx_svc.create(db, user.id, TransactionIn(**p))
        return {"transaction_id": tx.id}
    if action.tool == "update_transaction":
        tx = tx_svc.update(db, user.id, p["id"], TransactionUpdate(**p["changes"]))
        return {"transaction_id": tx.id}
    if action.tool == "delete_transaction":
        tx_svc.delete(db, user.id, p["id"])
        return {"deleted": p["id"]}
    if action.tool == "create_future_expense":
        if "recurrence" in p:
            data = RecurrenceIn(**p["recurrence"]).model_dump()
            get_owned(db, Account, data["account_id"], user.id, "Conta")
            rec = Recurrence(user_id=user.id, **data)
            db.add(rec)
            db.flush()
            audit.record(
                db,
                user.id,
                "recurrence",
                rec.id,
                "create",
                f"Recorrência criada pelo assistente: {rec.description}.",
            )
            db.commit()
            return {"recurrence_id": rec.id}
        tx = tx_svc.create(db, user.id, TransactionIn(**p["transaction"]))
        return {"transaction_id": tx.id}
    raise ToolError("Ação desconhecida.")


def expire_old(db: Session, user_id: str) -> None:
    for a in db.scalars(select(AIAction).where(AIAction.user_id == user_id, AIAction.status == "pending")):
        created = a.created_at if a.created_at.tzinfo else a.created_at.replace(tzinfo=utcnow().tzinfo)
        if utcnow() - created > timedelta(hours=24):
            a.status = "expired"


def as_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)
