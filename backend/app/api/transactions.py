from datetime import date
from typing import Literal

from fastapi import APIRouter, Query

from app.api.deps import DB, CurrentUser
from app.models import Transaction
from app.schemas import (
    PaymentMethod,
    TransactionIn,
    TransactionOut,
    TransactionPage,
    TransactionUpdate,
    TxStatus,
    TxType,
)
from app.services import transactions as svc
from app.services.ownership import get_owned

router = APIRouter(prefix="/api/transactions", tags=["lançamentos"])


@router.get("", response_model=TransactionPage)
def list_transactions(
    user: CurrentUser,
    db: DB,
    start: date | None = None,
    end: date | None = None,
    type: TxType | None = None,
    status: TxStatus | None = None,
    account_id: str | None = None,
    category_id: str | None = None,
    uncategorized: bool = False,
    payment_method: PaymentMethod | None = None,
    min_cents: int | None = Query(default=None, ge=0),
    max_cents: int | None = Query(default=None, ge=0),
    is_fixed: bool | None = None,
    recurring: bool = False,
    q: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    filters = {k: v for k, v in locals().items() if k not in ("user", "db", "page", "page_size")}
    return svc.list_filtered(db, user.id, filters, page, page_size)


@router.post("", response_model=TransactionOut, status_code=201)
def create_transaction(body: TransactionIn, user: CurrentUser, db: DB):
    return svc.to_out(db, svc.create(db, user.id, body))


@router.get("/{tx_id}", response_model=TransactionOut)
def get_transaction(tx_id: str, user: CurrentUser, db: DB):
    return svc.to_out(db, get_owned(db, Transaction, tx_id, user.id, "Lançamento"))


@router.patch("/{tx_id}", response_model=TransactionOut)
def update_transaction(tx_id: str, body: TransactionUpdate, user: CurrentUser, db: DB):
    return svc.to_out(db, svc.update(db, user.id, tx_id, body))


@router.delete("/{tx_id}")
def delete_transaction(tx_id: str, user: CurrentUser, db: DB, scope: Literal["one", "plan"] = "one"):
    return {"deleted": svc.delete(db, user.id, tx_id, scope)}


@router.post("/{tx_id}/restore", response_model=TransactionOut)
def restore_transaction(tx_id: str, user: CurrentUser, db: DB):
    return svc.to_out(db, svc.restore(db, user.id, tx_id))
