from fastapi import APIRouter

from app.api.deps import DB, CurrentUser
from app.errors import BadRequest
from app.models import Account, Category, Debt
from app.models.base import utcnow
from app.schemas import DebtIn, DebtPayIn, DebtUpdate
from app.services import audit
from app.services import debts as svc
from app.services import transactions as tx_svc
from app.services.dates import local_today
from app.services.money import brl
from app.services.ownership import get_owned

router = APIRouter(prefix="/api/debts", tags=["dívidas"])


def _refs(db, user_id: str, account_id: str | None, category_id: str | None) -> None:
    if account_id:
        get_owned(db, Account, account_id, user_id, "Conta")
    if category_id:
        cat = get_owned(db, Category, category_id, user_id, "Categoria")
        if cat.kind != "expense":
            raise BadRequest("Use uma categoria de despesa.")


def _out(debt: Debt, st: svc.DebtStatus) -> dict:
    return {
        "id": debt.id,
        "name": debt.name,
        "creditor": debt.creditor,
        "kind": debt.kind,
        "status": debt.status,
        "original_cents": debt.original_cents,
        "installments_total": debt.installments_total,
        "installment_cents": debt.installment_cents,
        "installments_paid_before": debt.installments_paid_before,
        "first_due_date": debt.first_due_date,
        "interest_monthly_bp": debt.interest_monthly_bp,
        "account_id": debt.account_id,
        "category_id": debt.category_id,
        "notes": debt.notes,
        "version": debt.version,
        # Calculados pelo sistema
        "paid_installments": st.paid_installments,
        "remaining_installments": st.remaining_installments,
        "paid_cents": st.paid_cents,
        "remaining_cents": st.remaining_cents,
        "total_cents": st.total_cents,
        "next_due": st.next_due,
        "end_date": st.end_date,
        "situation": st.situation,
        "overdue_installments": st.overdue_installments,
    }


def _one(db, user_id: str, debt_id: str) -> dict:
    for debt, st in svc.statuses(db, user_id, local_today()):
        if debt.id == debt_id:
            return _out(debt, st)
    raise BadRequest("Dívida não encontrada.")


@router.get("")
def list_debts(user: CurrentUser, db: DB):
    return [_out(d, s) for d, s in svc.statuses(db, user.id, local_today())]


@router.post("", status_code=201)
def create_debt(body: DebtIn, user: CurrentUser, db: DB):
    _refs(db, user.id, body.account_id, body.category_id)
    debt = Debt(user_id=user.id, **body.model_dump())
    db.add(debt)
    db.flush()
    audit.record(
        db,
        user.id,
        "debt",
        debt.id,
        "create",
        f'Dívida "{debt.name}" cadastrada: {debt.installments_total}x de {brl(debt.installment_cents)}.',
    )
    db.commit()
    return _one(db, user.id, debt.id)


@router.patch("/{debt_id}")
def update_debt(debt_id: str, body: DebtUpdate, user: CurrentUser, db: DB):
    debt = get_owned(db, Debt, debt_id, user.id, "Dívida")
    changes = body.model_dump(exclude_unset=True)
    _refs(db, user.id, changes.get("account_id"), changes.get("category_id"))
    before = {k: getattr(debt, k) for k in changes}
    for k, v in changes.items():
        setattr(debt, k, v)
    if debt.installments_paid_before > debt.installments_total:
        raise BadRequest("Parcelas já pagas não podem passar do total de parcelas.")
    audit.record(
        db, user.id, "debt", debt.id, "update", f'Dívida "{debt.name}" editada.', audit.diff(before, changes)
    )
    db.commit()
    return _one(db, user.id, debt.id)


@router.delete("/{debt_id}", status_code=204)
def delete_debt(debt_id: str, user: CurrentUser, db: DB):
    """Exclusão lógica. Pagamentos já registrados continuam no histórico."""
    debt = get_owned(db, Debt, debt_id, user.id, "Dívida")
    debt.deleted_at = utcnow()
    audit.record(db, user.id, "debt", debt.id, "delete", f'Dívida "{debt.name}" removida.')
    db.commit()


@router.post("/{debt_id}/pay", status_code=201)
def pay_installment(debt_id: str, body: DebtPayIn, user: CurrentUser, db: DB):
    tx = svc.pay(db, user.id, debt_id, body.amount_cents, body.occurred_on, body.account_id)
    return {"transaction": tx_svc.to_out(db, tx), "debt": _one(db, user.id, debt_id)}
