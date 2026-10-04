from datetime import date

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser
from app.errors import BadRequest
from app.models import Account, Transaction
from app.models.base import utcnow
from app.schemas import AccountIn, AccountOut, AccountUpdate, InvoiceOut
from app.services import audit, ledger
from app.services.cards import invoice_month_for
from app.services.dates import local_today
from app.services.ownership import get_owned

router = APIRouter(prefix="/api/accounts", tags=["contas"])


def build_out(db, account: Account, balances: dict[str, int], today: date) -> AccountOut:
    out = AccountOut.model_validate(account)
    out.balance_cents = balances.get(account.id, 0)
    if account.kind == "credit_card":
        # Limite usado inclui parcelas futuras: a compra inteira já compromete o limite
        all_dates = ledger.account_balances(db, account.user_id, None, include_pending=True)
        out.used_cents = max(0, -all_dates.get(account.id, 0))
        if account.credit_limit_cents is not None:
            out.available_cents = account.credit_limit_cents - out.used_cents
        current = invoice_month_for(today, account.closing_day)
        for inv in ledger.card_invoices(db, account):
            if inv["invoice_month"] == current:
                out.current_invoice = InvoiceOut(**inv)
    return out


@router.get("", response_model=list[AccountOut])
def list_accounts(user: CurrentUser, db: DB):
    today = local_today()
    balances = ledger.account_balances(db, user.id, as_of=today)
    accounts = db.scalars(
        select(Account)
        .where(Account.user_id == user.id, Account.deleted_at.is_(None))
        .order_by(Account.created_at)
    ).all()
    return [build_out(db, a, balances, today) for a in accounts]


@router.post("", response_model=AccountOut, status_code=201)
def create_account(body: AccountIn, user: CurrentUser, db: DB):
    data = body.model_dump()
    if body.kind != "credit_card":
        data.update(credit_limit_cents=None, closing_day=None, due_day=None)
    account = Account(user_id=user.id, **data)
    db.add(account)
    db.flush()
    audit.record(db, user.id, "account", account.id, "create", f'Conta "{account.name}" criada.')
    db.commit()
    today = local_today()
    return build_out(db, account, ledger.account_balances(db, user.id, as_of=today), today)


@router.patch("/{account_id}", response_model=AccountOut)
def update_account(account_id: str, body: AccountUpdate, user: CurrentUser, db: DB):
    account = get_owned(db, Account, account_id, user.id, "Conta")
    changes = body.model_dump(exclude_unset=True)
    if account.kind != "credit_card" and {"closing_day", "due_day", "credit_limit_cents"} & changes.keys():
        raise BadRequest("Limite, fechamento e vencimento só se aplicam a cartões.")
    before = {k: getattr(account, k) for k in changes}
    for k, v in changes.items():
        setattr(account, k, v)
    if account.kind == "credit_card" and (account.closing_day is None or account.due_day is None):
        raise BadRequest("Cartão de crédito precisa de dia de fechamento e de vencimento.")
    if "closing_day" in changes:
        # Recalcula a fatura das compras não parceladas
        for tx in db.scalars(
            select(Transaction).where(
                Transaction.account_id == account.id,
                Transaction.installment_plan_id.is_(None),
                Transaction.type.in_(("income", "expense")),
                Transaction.deleted_at.is_(None),
            )
        ):
            tx.invoice_month = invoice_month_for(tx.occurred_on, account.closing_day)
    audit.record(
        db,
        user.id,
        "account",
        account.id,
        "update",
        f'Conta "{account.name}" editada.',
        audit.diff(before, changes),
    )
    db.commit()
    today = local_today()
    return build_out(db, account, ledger.account_balances(db, user.id, as_of=today), today)


@router.delete("/{account_id}", status_code=204)
def delete_account(account_id: str, user: CurrentUser, db: DB):
    account = get_owned(db, Account, account_id, user.id, "Conta")
    remaining = db.scalar(
        select(func.count()).where(Account.user_id == user.id, Account.deleted_at.is_(None))
    )
    if remaining <= 1:
        raise BadRequest("Você precisa manter pelo menos uma conta.")
    # Exclusão lógica: o histórico de lançamentos é preservado
    account.deleted_at = utcnow()
    audit.record(db, user.id, "account", account.id, "delete", f'Conta "{account.name}" arquivada.')
    db.commit()


@router.get("/{account_id}/invoices", response_model=list[InvoiceOut])
def invoices(account_id: str, user: CurrentUser, db: DB):
    account = get_owned(db, Account, account_id, user.id, "Conta")
    if account.kind != "credit_card":
        raise BadRequest("Faturas existem apenas para cartões de crédito.")
    return [InvoiceOut(**i) for i in ledger.card_invoices(db, account)]
