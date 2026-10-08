"""Seus dados: exportação (CSV, Excel, PDF, JSON), backup/restauração e importação de extratos."""

import json
from datetime import date

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DB, CurrentUser
from app.errors import BadRequest
from app.models import Account, Transaction
from app.schemas import TransactionIn
from app.services import audit, backup, exporters, importers
from app.services import transactions as tx_svc
from app.services.dates import local_today
from app.services.ownership import get_owned

router = APIRouter(prefix="/api", tags=["dados"])

MAX_IMPORT = 10 * 1024 * 1024


def _download(body: bytes | str, media: str, filename: str) -> Response:
    return Response(
        body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.get("/export/transactions.csv")
def export_csv(user: CurrentUser, db: DB):
    return _download(
        backup.export_csv(db, user.id),
        "text/csv; charset=utf-8",
        f"julius-lancamentos-{local_today().isoformat()}.csv",
    )


@router.get("/export/transactions.xlsx")
def export_xlsx(user: CurrentUser, db: DB):
    return _download(
        exporters.transactions_xlsx(db, user.id),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        f"julius-lancamentos-{local_today().isoformat()}.xlsx",
    )


@router.get("/export/report.pdf")
def export_pdf(user: CurrentUser, db: DB, month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$")):
    ref = date.fromisoformat(f"{month}-01") if month else local_today()
    return _download(
        exporters.month_report_pdf(db, user, ref),
        "application/pdf",
        f"julius-relatorio-{ref.strftime('%Y-%m')}.pdf",
    )


@router.get("/export/backup.json")
def export_backup(user: CurrentUser, db: DB):
    body = json.dumps(backup.export_json(db, user), ensure_ascii=False, indent=1)
    return _download(body, "application/json", f"julius-backup-{local_today().isoformat()}.json")


@router.post("/import/backup")
async def import_backup(user: CurrentUser, db: DB, file: UploadFile = File(...)):
    raw = await file.read(50 * 1024 * 1024 + 1)
    if len(raw) > 50 * 1024 * 1024:
        raise BadRequest("Backup muito grande (limite 50 MB).")
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BadRequest("O arquivo não é um backup JSON válido.") from exc
    if not isinstance(payload, dict):
        raise BadRequest("O arquivo não é um backup JSON válido.")
    return {"inserted": backup.restore_json(db, user, payload)}


# ---------- Extratos bancários ----------
@router.post("/import/statement/preview")
async def statement_preview(
    user: CurrentUser, db: DB, file: UploadFile = File(...), account_id: str = Form(...)
):
    """Lê o extrato e mostra o que seria importado. NADA é gravado nesta etapa."""
    get_owned(db, Account, account_id, user.id, "Conta")
    data = await file.read(MAX_IMPORT + 1)
    if len(data) > MAX_IMPORT:
        raise BadRequest("Arquivo muito grande (limite 10 MB).")
    kind = importers.detect(file.filename or "", data)
    rows = importers.PARSERS[kind](data)
    items = importers.preview(db, user.id, account_id, rows)
    return {"format": kind, "items": items, "duplicates": sum(1 for i in items if i["duplicate"])}


class ImportItem(BaseModel):
    occurred_on: date
    amount_cents: int = Field(gt=0)
    type: str
    description: str = Field(min_length=1, max_length=200)
    category_id: str | None = None
    import_ref: str = Field(min_length=8, max_length=64)


class ImportConfirm(BaseModel):
    account_id: str
    items: list[ImportItem] = Field(max_length=5000)


@router.post("/import/statement/confirm")
def statement_confirm(body: ImportConfirm, user: CurrentUser, db: DB):
    get_owned(db, Account, body.account_id, user.id, "Conta")
    existing = set(
        db.scalars(
            select(Transaction.import_ref).where(
                Transaction.user_id == user.id, Transaction.import_ref.in_([i.import_ref for i in body.items])
            )
        )
    )
    created = skipped = 0
    for item in body.items:
        if item.import_ref in existing:
            skipped += 1
            continue
        data = TransactionIn(
            type="income" if item.type == "income" else "expense",
            account_id=body.account_id,
            amount_cents=item.amount_cents,
            occurred_on=item.occurred_on,
            description=item.description,
            category_id=item.category_id,
            source="import",
        )
        try:
            tx_svc.create(db, user.id, data, import_ref=item.import_ref)  # referência gravada junto
        except (BadRequest, IntegrityError):
            db.rollback()
            skipped += 1
            continue
        existing.add(item.import_ref)
        created += 1
    audit.record(
        db,
        user.id,
        "import",
        body.account_id,
        "create",
        f"Extrato importado: {created} lançamento(s), {skipped} ignorado(s).",
    )
    db.commit()
    return {"created": created, "skipped": skipped}
