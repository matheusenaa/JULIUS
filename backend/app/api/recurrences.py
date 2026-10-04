from datetime import date, timedelta

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.errors import BadRequest, Conflict
from app.models import Account, Category, Recurrence, Transaction
from app.models.base import utcnow
from app.schemas import (
    OccurrenceConfirmIn,
    OccurrenceOut,
    OccurrenceSkipIn,
    RecurrenceIn,
    RecurrenceOut,
    RecurrenceUpdate,
    TransactionOut,
)
from app.services import audit
from app.services import transactions as tx_svc
from app.services.cards import invoice_month_for
from app.services.dates import local_today
from app.services.ownership import get_owned
from app.services.recurrences import occurrence_dates, pending_occurrences

router = APIRouter(prefix="/api/recurrences", tags=["recorrências"])

LOOKBACK_DAYS = 62  # ocorrências atrasadas aparecem por até ~2 meses


def _validate_refs(db, user_id: str, account_id: str | None, category_id: str | None, tx_type: str):
    if account_id:
        get_owned(db, Account, account_id, user_id, "Conta")
    if category_id:
        cat = get_owned(db, Category, category_id, user_id, "Categoria")
        if cat.kind != tx_type:
            raise BadRequest("A categoria não corresponde ao tipo (receita/despesa).")


def _out(db, rec: Recurrence, today: date) -> RecurrenceOut:
    out = RecurrenceOut.model_validate(rec)
    upcoming = pending_occurrences(db, rec.user_id, today, today + timedelta(days=400))
    out.next_date = next((o.date for o in upcoming if o.recurrence.id == rec.id), None)
    return out


@router.get("", response_model=list[RecurrenceOut])
def list_recurrences(user: CurrentUser, db: DB):
    today = local_today()
    recs = db.scalars(
        select(Recurrence)
        .where(Recurrence.user_id == user.id, Recurrence.deleted_at.is_(None))
        .order_by(Recurrence.type, Recurrence.description)
    ).all()
    upcoming = pending_occurrences(db, user.id, today, today + timedelta(days=400))
    result = []
    for rec in recs:
        out = RecurrenceOut.model_validate(rec)
        out.next_date = next((o.date for o in upcoming if o.recurrence.id == rec.id), None)
        result.append(out)
    return result


@router.post("", response_model=RecurrenceOut, status_code=201)
def create_recurrence(body: RecurrenceIn, user: CurrentUser, db: DB):
    _validate_refs(db, user.id, body.account_id, body.category_id, body.type)
    data = body.model_dump()
    if data["frequency"] == "monthly" and not data["day_of_month"]:
        data["day_of_month"] = body.start_date.day
    rec = Recurrence(user_id=user.id, **data)
    db.add(rec)
    db.flush()
    audit.record(
        db,
        user.id,
        "recurrence",
        rec.id,
        "create",
        f"Recorrência criada: {rec.description} ({tx_svc.brl(rec.amount_cents)}).",
    )
    db.commit()
    return _out(db, rec, local_today())


@router.patch("/{rec_id}", response_model=RecurrenceOut)
def update_recurrence(rec_id: str, body: RecurrenceUpdate, user: CurrentUser, db: DB):
    rec = get_owned(db, Recurrence, rec_id, user.id, "Recorrência")
    changes = body.model_dump(exclude_unset=True)
    _validate_refs(db, user.id, changes.get("account_id"), changes.get("category_id"), rec.type)
    if changes.get("end_date") and changes["end_date"] < rec.start_date:
        raise BadRequest("A data final não pode ser anterior à inicial.")
    before = {k: getattr(rec, k) for k in changes}
    for k, v in changes.items():
        setattr(rec, k, v)
    # Só afeta previsões futuras; lançamentos já efetivados não mudam
    audit.record(
        db,
        user.id,
        "recurrence",
        rec.id,
        "update",
        f"Recorrência editada: {rec.description}.",
        audit.diff(before, changes),
    )
    db.commit()
    return _out(db, rec, local_today())


@router.delete("/{rec_id}", status_code=204)
def delete_recurrence(rec_id: str, user: CurrentUser, db: DB):
    rec = get_owned(db, Recurrence, rec_id, user.id, "Recorrência")
    rec.deleted_at = utcnow()
    audit.record(db, user.id, "recurrence", rec.id, "delete", f"Recorrência encerrada: {rec.description}.")
    db.commit()


@router.get("/occurrences", response_model=list[OccurrenceOut])
def occurrences(user: CurrentUser, db: DB, days: int = 31):
    today = local_today()
    days = max(1, min(days, 366))
    return [
        OccurrenceOut(
            recurrence_id=o.recurrence.id,
            date=o.date,
            type=o.recurrence.type,
            description=o.recurrence.description,
            amount_cents=o.recurrence.amount_cents,
            account_id=o.recurrence.account_id,
            category_id=o.recurrence.category_id,
            overdue=o.date < today,
        )
        for o in pending_occurrences(
            db, user.id, today - timedelta(days=LOOKBACK_DAYS), today + timedelta(days=days)
        )
    ]


def _existing(db, rec_id: str, when: date) -> Transaction | None:
    return db.scalar(
        select(Transaction).where(Transaction.recurrence_id == rec_id, Transaction.occurrence_date == when)
    )


def _check_occurrence(rec: Recurrence, when: date) -> None:
    if when not in occurrence_dates(rec, when, when):
        raise BadRequest("Esta data não corresponde a uma ocorrência da recorrência.")


@router.post("/{rec_id}/confirm", response_model=TransactionOut, status_code=201)
def confirm(rec_id: str, body: OccurrenceConfirmIn, user: CurrentUser, db: DB):
    """Efetiva a ocorrência: vira um lançamento real (uma única vez por data)."""
    rec = get_owned(db, Recurrence, rec_id, user.id, "Recorrência")
    _check_occurrence(rec, body.occurrence_date)
    account = get_owned(db, Account, body.account_id or rec.account_id, user.id, "Conta")
    occurred_on = body.occurred_on or body.occurrence_date
    tx = _existing(db, rec.id, body.occurrence_date)
    if tx is not None and tx.deleted_at is None:
        raise Conflict("Esta ocorrência já foi lançada.", code="already_confirmed")
    if tx is None:
        tx = Transaction(user_id=user.id, recurrence_id=rec.id, occurrence_date=body.occurrence_date)
        db.add(tx)
    else:  # estava marcada como pulada: reaproveita o registro
        tx.deleted_at = None
    tx.account_id = account.id
    tx.type = rec.type
    tx.status = "paid"
    tx.amount_cents = body.amount_cents or rec.amount_cents
    tx.occurred_on = occurred_on
    tx.description = rec.description
    tx.category_id = rec.category_id
    tx.payment_method = rec.payment_method or ("credit" if account.kind == "credit_card" else None)
    tx.is_fixed = rec.is_fixed
    tx.source = "recurrence"
    tx.invoice_month = (
        invoice_month_for(occurred_on, account.closing_day) if account.kind == "credit_card" else None
    )
    db.flush()
    audit.record(
        db,
        user.id,
        "transaction",
        tx.id,
        "create",
        f"Recorrência efetivada: {rec.description} ({tx_svc.brl(tx.amount_cents)}).",
    )
    db.commit()
    return tx_svc.to_out(db, tx)


@router.post("/{rec_id}/skip", status_code=204)
def skip(rec_id: str, body: OccurrenceSkipIn, user: CurrentUser, db: DB):
    """Pula uma ocorrência (ex.: mês sem cobrança). Fica registrado como lançamento excluído,
    o que impede que a previsão reapareça e permite desfazer depois."""
    rec = get_owned(db, Recurrence, rec_id, user.id, "Recorrência")
    _check_occurrence(rec, body.occurrence_date)
    if _existing(db, rec.id, body.occurrence_date) is not None:
        raise Conflict("Esta ocorrência já foi lançada ou pulada.")
    now = utcnow()
    tx = Transaction(
        user_id=user.id,
        recurrence_id=rec.id,
        occurrence_date=body.occurrence_date,
        account_id=rec.account_id,
        type=rec.type,
        status="pending",
        amount_cents=rec.amount_cents,
        occurred_on=body.occurrence_date,
        description=rec.description,
        category_id=rec.category_id,
        is_fixed=rec.is_fixed,
        source="recurrence",
        deleted_at=now,
    )
    db.add(tx)
    db.flush()
    audit.record(
        db,
        user.id,
        "recurrence",
        rec.id,
        "skip",
        f"Ocorrência de {body.occurrence_date.strftime('%d/%m/%Y')} pulada: {rec.description}.",
    )
    db.commit()
