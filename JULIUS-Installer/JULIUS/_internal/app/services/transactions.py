from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy import update as sa_update
from sqlalchemy.orm import Session

from app.errors import BadRequest, Conflict
from app.models import Account, Category, InstallmentPlan, Transaction
from app.models.base import utcnow
from app.schemas import TransactionIn, TransactionOut, TransactionUpdate
from app.services import audit, categorizer
from app.services.cards import invoice_month_for, split_installments
from app.services.dates import add_months, local_today
from app.services.money import brl  # noqa: F401 — reexportado (usado por outros módulos)
from app.services.ownership import get_owned

TYPE_PT = {"income": "Receita", "expense": "Despesa", "transfer": "Transferência"}
AUDITED_FIELDS = (
    "account_id",
    "to_account_id",
    "amount_cents",
    "occurred_on",
    "description",
    "notes",
    "category_id",
    "payment_method",
    "is_fixed",
    "status",
)


def _snapshot(tx: Transaction) -> dict:
    return {f: getattr(tx, f) for f in AUDITED_FIELDS}


def _check_category(db: Session, user_id: str, category_id: str | None, tx_type: str) -> None:
    if category_id is None:
        return
    if tx_type == "transfer":
        raise BadRequest("Transferências não têm categoria.", code="category_kind")
    cat = get_owned(db, Category, category_id, user_id, "Categoria")
    if tx_type in ("income", "expense") and cat.kind != tx_type:
        kind = "receita" if cat.kind == "income" else "despesa"
        raise BadRequest(f'A categoria "{cat.name}" é de {kind}.', code="category_kind")


def _invoice(account: Account, tx_type: str, occurred_on: date) -> date | None:
    if account.kind == "credit_card" and tx_type in ("income", "expense"):
        return invoice_month_for(occurred_on, account.closing_day)
    return None


def create(
    db: Session, user_id: str, data: TransactionIn, today: date | None = None, import_ref: str | None = None
) -> Transaction:
    today = today or local_today()
    if data.id:
        existing = db.get(Transaction, data.id)
        if existing is not None:
            if existing.user_id != user_id:
                raise Conflict("Identificador já utilizado.")
            return existing  # reenvio da fila offline: não duplica

    account = get_owned(db, Account, data.account_id, user_id, "Conta")
    if data.to_account_id:
        get_owned(db, Account, data.to_account_id, user_id, "Conta de destino")
    _check_category(db, user_id, data.category_id, data.type)

    payment = data.payment_method
    if payment is None and account.kind == "credit_card" and data.type == "expense":
        payment = "credit"

    common = dict(
        user_id=user_id,
        account_id=account.id,
        to_account_id=data.to_account_id,
        type=data.type,
        description=data.description,
        notes=data.notes,
        category_id=data.category_id,
        payment_method=payment,
        is_fixed=data.is_fixed,
        source=data.source,
    )
    if data.category_id and data.source in ("quick_input", "ai", "ocr"):
        # O usuário revisou e confirmou a categoria da sugestão: vira aprendizado
        categorizer.learn(db, user_id, data.description, data.category_id)

    if data.installments == 1:
        tx = Transaction(
            id=data.id,
            amount_cents=data.amount_cents,
            occurred_on=data.occurred_on,
            status=data.status,
            invoice_month=_invoice(account, data.type, data.occurred_on),
            import_ref=import_ref,
            **common,
        )
        db.add(tx)
        db.flush()
        audit.record(
            db,
            user_id,
            "transaction",
            tx.id,
            "create",
            f"{TYPE_PT[tx.type]} de {brl(tx.amount_cents)} criada: {tx.description}.",
        )
        db.commit()
        return tx

    # Parcelado: um plano + N transações com valores exatos e datas mensais
    plan = InstallmentPlan(
        user_id=user_id,
        account_id=account.id,
        description=data.description,
        total_cents=data.amount_cents,
        installments=data.installments,
        purchase_date=data.occurred_on,
    )
    db.add(plan)
    db.flush()
    first_invoice = _invoice(account, data.type, data.occurred_on)
    first = None
    for i, cents in enumerate(split_installments(data.amount_cents, data.installments)):
        when = add_months(data.occurred_on, i)
        # No cartão a dívida já existe (consome limite); fora dele, parcela futura é prevista
        status = "paid" if account.kind == "credit_card" or when <= today else "pending"
        if data.status in ("pending", "confirmed"):
            status = data.status
        tx = Transaction(
            id=data.id if i == 0 else None,
            amount_cents=cents,
            occurred_on=when,
            status=status,
            invoice_month=add_months(first_invoice, i) if first_invoice else None,
            installment_plan_id=plan.id,
            installment_number=i + 1,
            **{**common, "description": f"{data.description} ({i + 1}/{data.installments})"},
        )
        db.add(tx)
        first = first or tx
    db.flush()
    audit.record(
        db,
        user_id,
        "installment_plan",
        plan.id,
        "create",
        f"Compra parcelada de {brl(plan.total_cents)} em {plan.installments}x: {plan.description}.",
    )
    db.commit()
    return first


def update(db: Session, user_id: str, tx_id: str, data: TransactionUpdate) -> Transaction:
    tx = get_owned(db, Transaction, tx_id, user_id, "Lançamento")
    if data.version != tx.version:
        raise Conflict(
            "Este lançamento foi alterado em outro lugar. Recarregue para ver a versão atual.",
            code="version_conflict",
            details={"current": to_out(db, tx).model_dump(mode="json")},
        )
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    before = _snapshot(tx)

    if "to_account_id" in changes and tx.type != "transfer" and changes["to_account_id"]:
        raise BadRequest("Conta de destino só se aplica a transferências.")
    for key in ("account_id", "to_account_id"):
        if changes.get(key):
            get_owned(db, Account, changes[key], user_id, "Conta")
    if "category_id" in changes:
        _check_category(db, user_id, changes["category_id"], tx.type)

    for key, value in changes.items():
        setattr(tx, key, value)
    if tx.type == "transfer" and (not tx.to_account_id or tx.to_account_id == tx.account_id):
        raise BadRequest("Transferência precisa de uma conta de destino diferente da origem.")

    if {"account_id", "occurred_on"} & changes.keys() and tx.installment_plan_id is None:
        tx.invoice_month = _invoice(db.get(Account, tx.account_id), tx.type, tx.occurred_on)

    diff = audit.diff(before, _snapshot(tx))
    if not diff:
        return tx
    # A versão sobe automaticamente no flush (models.base._bump_versions)
    if "category_id" in diff and tx.category_id:
        categorizer.learn(db, user_id, tx.description, tx.category_id)
        old = db.get(Category, before["category_id"]) if before["category_id"] else None
        new = db.get(Category, tx.category_id)
        summary = f'Categoria alterada de "{old.name if old else "sem categoria"}" para "{new.name}".'
    else:
        summary = f"{TYPE_PT[tx.type]} editada: {tx.description}."
    audit.record(db, user_id, "transaction", tx.id, "update", summary, diff)
    db.commit()
    return tx


def delete(db: Session, user_id: str, tx_id: str, scope: str = "one") -> int:
    tx = get_owned(db, Transaction, tx_id, user_id, "Lançamento")
    now = utcnow()
    if scope == "plan" and tx.installment_plan_id:
        # Esta parcela e as seguintes
        result = db.execute(
            sa_update(Transaction)
            .where(
                Transaction.installment_plan_id == tx.installment_plan_id,
                Transaction.installment_number >= tx.installment_number,
                Transaction.deleted_at.is_(None),
            )
            # UPDATE em massa não passa pelo ORM: versão e updated_at à mão (sincronização)
            .values(deleted_at=now, updated_at=now, version=Transaction.version + 1)
        )
        count = result.rowcount
        summary = f"{count} parcela(s) excluída(s): {tx.description}."
    else:
        tx.deleted_at = now
        count = 1
        summary = f"{TYPE_PT[tx.type]} de {brl(tx.amount_cents)} excluída: {tx.description}."
    audit.record(db, user_id, "transaction", tx.id, "delete", summary)
    db.commit()
    return count


def restore(db: Session, user_id: str, tx_id: str) -> Transaction:
    tx = db.get(Transaction, tx_id)
    if tx is None or tx.user_id != user_id or tx.deleted_at is None:
        raise BadRequest("Nada para desfazer.")
    tx.deleted_at = None
    audit.record(db, user_id, "transaction", tx.id, "restore", f"Lançamento restaurado: {tx.description}.")
    db.commit()
    return tx


def to_out(db: Session, tx: Transaction, plans: dict[str, int] | None = None) -> TransactionOut:
    out = TransactionOut.model_validate(tx)
    if tx.installment_plan_id:
        if plans is None or tx.installment_plan_id not in plans:
            plan = db.get(InstallmentPlan, tx.installment_plan_id)
            out.installment_total = plan.installments if plan else None
        else:
            out.installment_total = plans[tx.installment_plan_id]
    return out


def list_filtered(db: Session, user_id: str, f: dict, page: int, page_size: int):
    cond = [Transaction.user_id == user_id, Transaction.deleted_at.is_(None)]
    if f.get("start"):
        cond.append(Transaction.occurred_on >= f["start"])
    if f.get("end"):
        cond.append(Transaction.occurred_on <= f["end"])
    if f.get("type"):
        cond.append(Transaction.type == f["type"])
    if f.get("status"):
        cond.append(Transaction.status == f["status"])
    if f.get("account_id"):
        cond.append(
            or_(Transaction.account_id == f["account_id"], Transaction.to_account_id == f["account_id"])
        )
    if f.get("category_id"):
        children = select(Category.id).where(Category.parent_id == f["category_id"])
        cond.append(or_(Transaction.category_id == f["category_id"], Transaction.category_id.in_(children)))
    if f.get("uncategorized"):
        cond.append(Transaction.category_id.is_(None))
        cond.append(Transaction.type != "transfer")
    if f.get("payment_method"):
        cond.append(Transaction.payment_method == f["payment_method"])
    if f.get("min_cents") is not None:
        cond.append(Transaction.amount_cents >= f["min_cents"])
    if f.get("max_cents") is not None:
        cond.append(Transaction.amount_cents <= f["max_cents"])
    if f.get("is_fixed") is not None:
        cond.append(Transaction.is_fixed == f["is_fixed"])
    if f.get("recurring"):
        cond.append(or_(Transaction.recurrence_id.is_not(None), Transaction.installment_plan_id.is_not(None)))
    if f.get("q"):
        cond.append(
            or_(
                func.lower(Transaction.description).contains(f["q"].lower(), autoescape=True),
                func.lower(Transaction.notes).contains(f["q"].lower(), autoescape=True),
            )
        )

    total = db.scalar(select(func.count()).select_from(Transaction).where(*cond))
    sums = dict(
        db.execute(
            select(Transaction.type, func.sum(Transaction.amount_cents))
            # Cancelados aparecem na lista, mas não somam
            .where(*cond, Transaction.type.in_(("income", "expense")), Transaction.status != "canceled")
            .group_by(Transaction.type)
        ).all()
    )
    rows = db.scalars(
        select(Transaction)
        .where(*cond)
        .order_by(Transaction.occurred_on.desc(), Transaction.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    plan_ids = {t.installment_plan_id for t in rows if t.installment_plan_id}
    plans = (
        dict(
            db.execute(
                select(InstallmentPlan.id, InstallmentPlan.installments).where(
                    InstallmentPlan.id.in_(plan_ids)
                )
            ).all()
        )
        if plan_ids
        else {}
    )
    return {
        "items": [to_out(db, t, plans) for t in rows],
        "total": total or 0,
        "page": page,
        "page_size": page_size,
        "income_cents": int(sums.get("income") or 0),
        "expense_cents": int(sums.get("expense") or 0),
    }
