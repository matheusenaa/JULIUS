"""Cálculo de saldos. Fonte única da verdade: as transações.

Saldos nunca são gravados; são somados pelo banco a cada consulta. Para o volume
de uma pessoa isso leva milissegundos e elimina saldo dessincronizado.
"""

from collections import defaultdict
from datetime import date

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import Account, Transaction
from app.services.cards import due_date
from app.services.reqcache import cached


def _active_tx(user_id: str):
    """Transações que existem para fins financeiros: não excluídas e não canceladas."""
    return (
        Transaction.user_id == user_id,
        Transaction.deleted_at.is_(None),
        Transaction.status != "canceled",
    )


def cash_accounts(db: Session, user_id: str) -> dict[str, Account]:
    """Contas que compõem o "dinheiro disponível" (exclui cartões e contas fora do total)."""
    return {
        a.id: a
        for a in db.scalars(
            select(Account).where(
                Account.user_id == user_id,
                Account.deleted_at.is_(None),
                Account.kind != "credit_card",
                Account.include_in_total.is_(True),
            )
        )
    }


def cards(db: Session, user_id: str) -> list[Account]:
    return list(
        db.scalars(
            select(Account).where(
                Account.user_id == user_id, Account.deleted_at.is_(None), Account.kind == "credit_card"
            )
        )
    )


def cash_balance(db: Session, user_id: str, today: date) -> int:
    balances = account_balances(db, user_id, as_of=today)
    return sum(balances.get(a, 0) for a in cash_accounts(db, user_id))


def account_balances(
    db: Session, user_id: str, as_of: date | None = None, include_pending: bool = False
) -> dict[str, int]:
    """Saldo por conta: inicial + receitas − despesas − transferências enviadas + recebidas."""
    key = ("balances", user_id, as_of, include_pending)
    return dict(cached(db, key, lambda: _account_balances(db, user_id, as_of, include_pending)))


def _account_balances(db: Session, user_id: str, as_of: date | None, include_pending: bool) -> dict[str, int]:
    accounts = db.scalars(
        select(Account).where(Account.user_id == user_id, Account.deleted_at.is_(None))
    ).all()
    balances = {a.id: a.initial_balance_cents for a in accounts}

    filters = list(_active_tx(user_id))
    if not include_pending:
        filters.append(Transaction.status == "paid")
    if as_of is not None:
        filters.append(Transaction.occurred_on <= as_of)

    signed = case(
        (Transaction.type == "income", Transaction.amount_cents),
        else_=-Transaction.amount_cents,  # despesa e transferência saem da conta de origem
    )
    for account_id, total in db.execute(
        select(Transaction.account_id, func.sum(signed)).where(*filters).group_by(Transaction.account_id)
    ):
        if account_id in balances:
            balances[account_id] += int(total or 0)

    for account_id, total in db.execute(
        select(Transaction.to_account_id, func.sum(Transaction.amount_cents))
        .where(*filters, Transaction.type == "transfer")
        .group_by(Transaction.to_account_id)
    ):
        if account_id in balances:
            balances[account_id] += int(total or 0)
    return balances


def card_amount_due_by(db: Session, card: Account, until: date) -> int:
    """Quanto do cartão vence até `until` e ainda não foi pago.

    Pagamentos (transferências para o cartão) quitam as faturas mais antigas primeiro.
    Usa o mesmo cálculo da lista de faturas para os dois nunca divergirem.
    """
    return sum(i["remaining_cents"] for i in card_invoices(db, card) if i["due_date"] <= until)


def card_invoices(db: Session, card: Account) -> list[dict]:
    """Faturas do cartão, com total e situação (paga / aberta / futura)."""
    return [dict(i) for i in cached(db, ("invoices", card.id), lambda: _card_invoices(db, card))]


def _card_invoices(db: Session, card: Account) -> list[dict]:
    rows = db.execute(
        select(
            Transaction.invoice_month,
            func.sum(
                case(
                    (Transaction.type == "expense", Transaction.amount_cents),
                    (Transaction.type == "income", -Transaction.amount_cents),
                    else_=0,
                )
            ),
        )
        .where(
            *_active_tx(card.user_id),
            Transaction.account_id == card.id,
            Transaction.invoice_month.is_not(None),
        )
        .group_by(Transaction.invoice_month)
        .order_by(Transaction.invoice_month)
    ).all()
    paid_pool = int(
        db.scalar(
            select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
                *_active_tx(card.user_id),
                Transaction.type == "transfer",
                Transaction.to_account_id == card.id,
                Transaction.status == "paid",
            )
        )
        or 0
    )
    invoices = []
    for month, total in rows:
        total = int(total or 0)
        covered = min(paid_pool, max(total, 0))
        paid_pool -= covered
        invoices.append(
            {
                "invoice_month": month,
                "due_date": due_date(month, card.closing_day, card.due_day),
                "total_cents": total,
                "paid_cents": covered,
                "remaining_cents": max(total - covered, 0),
            }
        )
    return invoices


def totals_by_type(db: Session, user_id: str, start: date, end: date) -> dict[str, int]:
    """Receitas e despesas realizadas no período. Transferências NÃO entram."""
    result: dict[str, int] = defaultdict(int)
    for tx_type, total in db.execute(
        select(Transaction.type, func.sum(Transaction.amount_cents))
        .where(
            *_active_tx(user_id),
            Transaction.status == "paid",
            Transaction.type.in_(("income", "expense")),
            Transaction.occurred_on.between(start, end),
        )
        .group_by(Transaction.type)
    ):
        result[tx_type] = int(total or 0)
    return {"income": result["income"], "expense": result["expense"]}
