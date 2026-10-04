"""Comprovantes (OCR), anexos, exportação e backup."""

import hashlib
import json
import logging

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select

from app.ai.providers import AIUnavailable
from app.ai.receipt import read_receipt, sniff
from app.api.deps import DB, CurrentUser
from app.config import get_settings
from app.errors import AppError, BadRequest
from app.models import Attachment, Transaction
from app.security.ratelimit import ai_limiter
from app.services import audit, backup
from app.services.dates import local_today
from app.services.ownership import get_owned

router = APIRouter(prefix="/api", tags=["dados"])
log = logging.getLogger("julius.data")


async def _read_upload(file: UploadFile) -> tuple[bytes, str]:
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise BadRequest(f"Arquivo muito grande. Limite: {get_settings().max_upload_mb} MB.")
    if not data:
        raise BadRequest("Arquivo vazio.")
    mime = sniff(data)  # confia no conteúdo, não na extensão informada
    if mime is None:
        raise BadRequest("Formato não suportado. Envie JPG, PNG, WEBP ou PDF.")
    return data, mime


def _attachment_out(a: Attachment) -> dict:
    return {
        "id": a.id,
        "filename": a.filename,
        "content_type": a.content_type,
        "size_bytes": a.size_bytes,
        "transaction_id": a.transaction_id,
        "created_at": a.created_at,
    }


@router.post("/receipts/scan")
async def scan_receipt(user: CurrentUser, db: DB, file: UploadFile = File(...)):
    """Guarda o comprovante e devolve uma PROPOSTA de lançamento para confirmação."""
    if not ai_limiter.hit(user.id):
        raise AppError(429, "rate_limited", "Muitas leituras em pouco tempo. Aguarde um minuto.")
    data, mime = await _read_upload(file)
    attachment = Attachment(
        user_id=user.id,
        filename=(file.filename or "comprovante")[:200],
        content_type=mime,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        data=data,
    )
    db.add(attachment)
    db.flush()
    proposal, error = None, None
    try:
        proposal = read_receipt(db, user, data, mime, local_today())
        attachment.extracted = proposal.pop("raw", None)
    except AIUnavailable as exc:
        error = (
            str(exc)
            if "precisa" in str(exc)
            else "Não foi possível ler o comprovante agora. Preencha manualmente."
        )
        log.info("OCR indisponível: %s", exc)
    db.commit()
    return {"attachment": _attachment_out(attachment), "proposal": proposal, "error": error}


@router.post("/attachments", status_code=201)
async def upload_attachment(
    user: CurrentUser, db: DB, file: UploadFile = File(...), transaction_id: str | None = None
):
    if transaction_id:
        get_owned(db, Transaction, transaction_id, user.id, "Lançamento")
    data, mime = await _read_upload(file)
    a = Attachment(
        user_id=user.id,
        transaction_id=transaction_id,
        filename=(file.filename or "arquivo")[:200],
        content_type=mime,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        data=data,
    )
    db.add(a)
    db.flush()
    audit.record(db, user.id, "attachment", a.id, "create", f'Anexo "{a.filename}" adicionado.')
    db.commit()
    return _attachment_out(a)


class LinkIn(BaseModel):
    transaction_id: str | None


@router.patch("/attachments/{attachment_id}")
def link_attachment(attachment_id: str, body: LinkIn, user: CurrentUser, db: DB):
    a = get_owned(db, Attachment, attachment_id, user.id, "Anexo")
    if body.transaction_id:
        get_owned(db, Transaction, body.transaction_id, user.id, "Lançamento")
    a.transaction_id = body.transaction_id
    db.commit()
    return _attachment_out(a)


@router.get("/attachments")
def list_attachments(user: CurrentUser, db: DB, transaction_id: str):
    return [
        _attachment_out(a)
        for a in db.scalars(
            select(Attachment).where(
                Attachment.user_id == user.id, Attachment.transaction_id == transaction_id
            )
        )
    ]


@router.get("/attachments/{attachment_id}/file")
def download_attachment(attachment_id: str, user: CurrentUser, db: DB):
    a = get_owned(db, Attachment, attachment_id, user.id, "Anexo")
    safe_name = "".join(ch for ch in a.filename if ch.isalnum() or ch in "._- ")[:100] or "anexo"
    return Response(
        a.data,
        media_type=a.content_type,
        headers={
            "Content-Disposition": f'inline; filename="{safe_name}"',
            "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'",
        },
    )


@router.delete("/attachments/{attachment_id}", status_code=204)
def delete_attachment(attachment_id: str, user: CurrentUser, db: DB):
    a = get_owned(db, Attachment, attachment_id, user.id, "Anexo")
    db.delete(a)
    audit.record(db, user.id, "attachment", attachment_id, "delete", f'Anexo "{a.filename}" removido.')
    db.commit()


@router.get("/export/transactions.csv")
def export_csv(user: CurrentUser, db: DB):
    filename = f"julius-lancamentos-{local_today().isoformat()}.csv"
    return Response(
        backup.export_csv(db, user.id),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/backup.json")
def export_backup(user: CurrentUser, db: DB):
    filename = f"julius-backup-{local_today().isoformat()}.json"
    body = json.dumps(backup.export_json(db, user), ensure_ascii=False, indent=1)
    return Response(
        body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
