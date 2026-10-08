"""Dívidas: tudo que é "quanto falta" é calculado, nunca digitado.

Parcelas pagas = pagas antes de cadastrar no JULIUS + pagamentos registrados
(lançamentos realizados ligados à dívida). Excluir um pagamento "devolve" a parcela.
"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import BadRequest, Conflict
from app.models import Account, Debt, Transaction
from app.services import audit
from app.services.cards import invoice_month_for
from app.services.dates import add_months, local_today
from app.services.ownership import get_owned


@dataclass
class DebtStatus:
    paid_installments: int
    remaining_installments: int
    paid_cents: int
    remaining_cents: int
    total_cents: int
    next_due: date | None
    end_date: date
    situation: str  # em_dia | atrasada | quitada | cancelada
    overdue_installments: int


def _payments(db: Session, debt_ids: list[str]) -> dict[str, tuple[int, int]]:
    if not debt_ids:
        return {}
    rows = db.execute(
        select(Transaction.debt_id, func.count(), func.coalesce(func.sum(Transaction.amount_cents), 0))
        .where(
            Transaction.debt_id.in_(debt_ids),
            Transaction.deleted_at.is_(None),
            Transaction.status == "paid",
        )
        .group_by(Transaction.debt_id)
    ).all()
    return {debt_id: (int(n), int(total)) for debt_id, n, total in rows}


def compute(debt: Debt, n_payments: int, paid_amount: int, today: date) -> DebtStatus:
    total = debt.installments_total * debt.installment_cents
    paid_installments = min(debt.installments_total, debt.installments_paid_before + n_payments)
    remaining_installments = debt.installments_total - paid_installments
    paid_cents = debt.installments_paid_before * debt.installment_cents + paid_amount
    remaining_cents = 0 if remaining_installments == 0 else max(0, total - paid_cents)
    next_due = add_months(debt.first_due_date, paid_installments) if remaining_installments else None
    end_date = add_months(debt.first_due_date, debt.installments_total - 1)
    overdue = 0
    if next_due:
        d = next_due
        while d < today and overdue < remaining_installments:
            overdue += 1
            d = add_months(debt.first_due_date, paid_installments + overdue)
    if debt.status == "canceled":
        situation = "cancelada"
    elif remaining_installments == 0:
        situation = "quitada"
    elif overdue:
        situation = "atrasada"
    else:
        situation = "em_dia"
    return DebtStatus(
        paid_installments=paid_installments,
        remaining_installments=remaining_installments,
        paid_cents=paid_cents,
        remaining_cents=remaining_cents,
        total_cents=total,
        next_due=next_due,
        end_date=end_date,
        situation=situation,
        overdue_installments=overdue,
    )


def statuses(db: Session, user_id: str, today: date | None = None) -> list[tuple[Debt, DebtStatus]]:
    today = today or local_today()
    debts = db.scalars(
        select(Debt).where(Debt.user_id == user_id, Debt.deleted_at.is_(None)).order_by(Debt.first_due_date)
    ).all()
    pays = _payments(db, [d.id for d in debts])
    return [(d, compute(d, *pays.get(d.id, (0, 0)), today)) for d in debts]


def upcoming_installments(
    db: Session, user_id: str, until: date, today: date
) -> list[tuple[Debt, date, int]]:
    """Parcelas ainda não pagas com vencimento até `until` (inclui atrasadas)."""
    out = []
    for debt, st in statuses(db, user_id, today):
        if debt.status != "active" or not st.remaining_installments:
            continue
        for i in range(st.remaining_installments):
            due = add_months(debt.first_due_date, st.paid_installments + i)
            if due > until:
                break
            out.append((debt, due, st.paid_installments + i + 1))
    return out


def pay(
    db: Session,
    user_id: str,
    debt_id: str,
    amount_cents: int | None,
    occurred_on: date | None,
    account_id: str | None,
) -> Transaction:
    """Registra o pagamento da próxima parcela como despesa realizada ligada à dívida."""
    debt = get_owned(db, Debt, debt_id, user_id, "Dívida")
    if debt.status != "active":
        raise BadRequest("Esta dívida está cancelada.")
    n, paid = _payments(db, [debt.id]).get(debt.id, (0, 0))
    st = compute(debt, n, paid, local_today())
    if st.remaining_installments == 0:
        raise Conflict("Esta dívida já está quitada.", code="debt_paid_off")
    account = get_owned(db, Account, account_id or debt.account_id, user_id, "Conta para pagamento")
    number = st.paid_installments + 1
    # Uma parcela excluída deixa um registro (excluído) com o mesmo número: reaproveita
    existing = db.scalar(
        select(Transaction).where(Transaction.debt_id == debt.id, Transaction.debt_installment == number)
    )
    tx = existing or Transaction(user_id=user_id, debt_id=debt.id, debt_installment=number)
    if existing is None:
        db.add(tx)
    tx.deleted_at = None
    tx.account_id = account.id
    tx.type = "expense"
    tx.status = "paid"
    tx.amount_cents = amount_cents or debt.installment_cents
    tx.occurred_on = occurred_on or local_today()
    tx.description = f"{debt.name} ({number}/{debt.installments_total})"
    tx.category_id = debt.category_id
    tx.payment_method = "credit" if account.kind == "credit_card" else tx.payment_method
    tx.is_fixed = True
    tx.source = "manual"
    if account.kind == "credit_card":
        tx.invoice_month = invoice_month_for(tx.occurred_on, account.closing_day)
    db.flush()
    audit.record(
        db,
        user_id,
        "debt",
        debt.id,
        "pay",
        f'Parcela {number}/{debt.installments_total} de "{debt.name}" paga.',
    )
    db.commit()
    return tx
