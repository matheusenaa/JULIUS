"""Documentos financeiros: contas, boletos, comprovantes, notas (foto, câmera, upload).

Fluxo: enviar → JULIUS lê (regras de PDF/boleto e/ou IA) → usuário revisa →
confirma (vira lançamento ou recorrência) | edita | descarta.
"""

import hashlib
import logging
from typing import Literal

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select

from app.ai.providers import AIUnavailable
from app.ai.receipt import EXTENSIONS, analyze, read_receipt, sniff
from app.api.deps import DB, CurrentUser
from app.config import get_settings
from app.errors import AppError, BadRequest
from app.models import Account, Attachment, Recurrence, Transaction
from app.models.activity import DOC_KINDS
from app.models.base import utcnow
from app.schemas import RecurrenceIn, TransactionIn
from app.security.ratelimit import ai_limiter
from app.services import audit, storage
from app.services import transactions as tx_svc
from app.services.dates import local_today
from app.services.ownership import get_owned

router = APIRouter(prefix="/api", tags=["documentos"])
log = logging.getLogger("julius.documents")


async def _read_upload(file: UploadFile) -> tuple[bytes, str]:
    """Valida tamanho, conteúdo real (assinatura do arquivo) e extensão."""
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise BadRequest(f"Arquivo muito grande. Limite: {get_settings().max_upload_mb} MB.")
    if not data:
        raise BadRequest("Arquivo vazio ou envio interrompido. Tente novamente.")
    mime = sniff(data)  # confia no conteúdo, não no que o navegador declarou
    if mime is None:
        raise BadRequest("Formato não suportado. Envie JPG, PNG, WEBP ou PDF.")
    name = (file.filename or "").lower()
    if "." in name and not name.endswith(EXTENSIONS[mime]):
        raise BadRequest("A extensão do arquivo não corresponde ao conteúdo. Envie o arquivo original.")
    if mime == "application/pdf" and b"%%EOF" not in data[-2048:]:
        raise BadRequest("O PDF parece incompleto (envio interrompido?). Tente novamente.")
    return data, mime


def _safe_name(name: str | None, default: str) -> str:
    cleaned = "".join(ch for ch in (name or "") if ch.isalnum() or ch in "._- ").strip()
    return (cleaned or default)[:200]


def _new_attachment(db, user_id: str, data: bytes, mime: str, filename: str, **extra) -> Attachment:
    att = Attachment(
        user_id=user_id,
        filename=filename,
        content_type=mime,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        **extra,
    )
    storage.save(att, data)
    db.add(att)
    db.flush()
    return att


def _doc_out(a: Attachment) -> dict:
    ex = a.extracted or {}
    return {
        "id": a.id,
        "filename": a.filename,
        "content_type": a.content_type,
        "size_bytes": a.size_bytes,
        "title": a.title or ex.get("title"),
        "kind": a.kind,
        "status": a.status,
        "transaction_id": a.transaction_id,
        "created_at": a.created_at,
        "amount_cents": ex.get("amount_cents"),
        "due_date": ex.get("due_date"),
        "beneficiary": ex.get("beneficiary"),
        "institution": ex.get("institution"),
        "barcode": ex.get("barcode"),
        "barcode_valid": ex.get("barcode_valid"),
        "document_number": ex.get("document_number"),
        "pix_key": ex.get("pix_key"),
        "engine": ex.get("engine"),
        "warnings": ex.get("warnings", []),
        "linked_recurrence_id": ex.get("linked_recurrence_id"),
    }


def _analyze_into(db, user, att: Attachment, data: bytes) -> tuple[dict | None, str | None]:
    try:
        extraction, proposal = analyze(db, user, data, att.content_type, local_today())
    except AIUnavailable as exc:
        att.status = "review"
        return None, str(exc)
    att.extracted = {**(att.extracted or {}), **extraction}
    if extraction.get("kind") and att.kind == "other":
        att.kind = extraction["kind"]
    att.title = att.title or extraction.get("title")
    att.status = "review"
    return proposal, None


def _limit(user_id: str) -> None:
    if not ai_limiter.hit(user_id):
        raise AppError(429, "rate_limited", "Muitas leituras em pouco tempo. Aguarde um minuto.")


# ---------- Documentos ----------
@router.get("/documents")
def list_documents(
    user: CurrentUser,
    db: DB,
    kind: str | None = None,
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
):
    cond = [Attachment.user_id == user.id, Attachment.deleted_at.is_(None)]
    if kind:
        cond.append(Attachment.kind == kind)
    if status:
        cond.append(Attachment.status == status)
    total = db.scalar(select(func.count()).select_from(Attachment).where(*cond))
    rows = db.scalars(
        select(Attachment)
        .where(*cond)
        .order_by(Attachment.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return {"items": [_doc_out(a) for a in rows], "total": total, "page": page, "page_size": page_size}


@router.post("/documents", status_code=201)
async def upload_document(
    user: CurrentUser,
    db: DB,
    file: UploadFile = File(...),
    kind: str | None = Form(default=None),
    title: str | None = Form(default=None),
    analyze_now: bool = Form(default=True),
):
    if kind and kind not in DOC_KINDS:
        raise BadRequest("Tipo de documento inválido.")
    data, mime = await _read_upload(file)
    att = _new_attachment(
        db,
        user.id,
        data,
        mime,
        _safe_name(file.filename, "documento"),
        kind=kind or "other",
        title=(title or None) and title[:120],
    )
    proposal, error = None, None
    if analyze_now:
        _limit(user.id)
        proposal, error = _analyze_into(db, user, att, data)
    audit.record(
        db, user.id, "document", att.id, "create", f'Documento "{att.title or att.filename}" adicionado.'
    )
    db.commit()
    return {"document": _doc_out(att), "proposal": proposal, "error": error}


@router.get("/documents/{doc_id}")
def get_document(doc_id: str, user: CurrentUser, db: DB):
    return _doc_out(get_owned(db, Attachment, doc_id, user.id, "Documento"))


@router.post("/documents/{doc_id}/analyze")
def reanalyze(doc_id: str, user: CurrentUser, db: DB):
    att = get_owned(db, Attachment, doc_id, user.id, "Documento")
    _limit(user.id)
    proposal, error = _analyze_into(db, user, att, storage.load(att))
    db.commit()
    return {"document": _doc_out(att), "proposal": proposal, "error": error}


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    kind: Literal["receipt", "bill", "invoice", "pix", "statement", "contract", "other"] | None = None
    transaction_id: str | None = None


@router.patch("/documents/{doc_id}")
def update_document(doc_id: str, body: DocumentUpdate, user: CurrentUser, db: DB):
    att = get_owned(db, Attachment, doc_id, user.id, "Documento")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("transaction_id"):
        get_owned(db, Transaction, changes["transaction_id"], user.id, "Lançamento")
    for k, v in changes.items():
        setattr(att, k, v)
    db.commit()
    return _doc_out(att)


class ConfirmIn(BaseModel):
    """Lançamento revisado pelo usuário, ou recorrência (contas mensais)."""

    transaction: dict | None = None
    recurrence: dict | None = None


@router.post("/documents/{doc_id}/confirm")
def confirm_document(doc_id: str, body: ConfirmIn, user: CurrentUser, db: DB):
    att = get_owned(db, Attachment, doc_id, user.id, "Documento")
    if att.status == "confirmed":
        raise AppError(409, "already_confirmed", "Este documento já foi confirmado.")
    if not body.transaction and not body.recurrence:
        raise BadRequest("Informe o lançamento ou a recorrência a criar.")
    try:
        tx_data = TransactionIn(**{**body.transaction, "source": "ocr"}) if body.transaction else None
        rec_data = RecurrenceIn(**body.recurrence) if body.recurrence else None
    except ValidationError as exc:
        raise BadRequest("Revise os campos: " + "; ".join(e["msg"] for e in exc.errors())[:250]) from exc
    result: dict = {}
    if rec_data:
        get_owned(db, Account, rec_data.account_id, user.id, "Conta")
        rec = Recurrence(user_id=user.id, **rec_data.model_dump())
        db.add(rec)
        db.flush()
        att.extracted = {**(att.extracted or {}), "linked_recurrence_id": rec.id}
        audit.record(
            db,
            user.id,
            "recurrence",
            rec.id,
            "create",
            f"Recorrência criada a partir de documento: {rec.description}.",
        )
        result["recurrence_id"] = rec.id
    att.status = "confirmed"
    db.commit()
    if tx_data:
        tx = tx_svc.create(db, user.id, tx_data)
        att = get_owned(db, Attachment, doc_id, user.id, "Documento")
        att.transaction_id = tx.id
        db.commit()
        result["transaction_id"] = tx.id
    return {"document": _doc_out(att), **result}


@router.post("/documents/{doc_id}/discard")
def discard_document(doc_id: str, user: CurrentUser, db: DB):
    att = get_owned(db, Attachment, doc_id, user.id, "Documento")
    att.status = "discarded"
    db.commit()
    return _doc_out(att)


@router.delete("/documents/{doc_id}", status_code=204)
def delete_document(doc_id: str, user: CurrentUser, db: DB):
    """Apaga o ARQUIVO de verdade (privacidade); o registro fica marcado como excluído."""
    att = get_owned(db, Attachment, doc_id, user.id, "Documento")
    storage.delete(att)
    att.deleted_at = utcnow()
    att.extracted = None
    audit.record(
        db, user.id, "document", att.id, "delete", f'Documento "{att.title or att.filename}" excluído.'
    )
    db.commit()


# ---------- Compatibilidade: comprovantes e anexos (endpoints anteriores) ----------
@router.post("/receipts/scan")
async def scan_receipt(user: CurrentUser, db: DB, file: UploadFile = File(...)):
    """Guarda o comprovante e devolve uma PROPOSTA de lançamento para confirmação."""
    _limit(user.id)
    data, mime = await _read_upload(file)
    att = _new_attachment(db, user.id, data, mime, _safe_name(file.filename, "comprovante"), status="review")
    proposal, error = None, None
    try:
        proposal = read_receipt(db, user, data, mime, local_today())
        att.extracted = proposal.pop("raw", None)
        att.kind = (att.extracted or {}).get("kind") or att.kind
        att.title = (att.extracted or {}).get("title")
    except AIUnavailable as exc:
        error = str(exc)
        log.info("Leitura indisponível: %s", exc)
    db.commit()
    return {"attachment": _attachment_out(att), "proposal": proposal, "error": error}


def _attachment_out(a: Attachment) -> dict:
    return {
        "id": a.id,
        "filename": a.filename,
        "content_type": a.content_type,
        "size_bytes": a.size_bytes,
        "transaction_id": a.transaction_id,
        "created_at": a.created_at,
    }


@router.post("/attachments", status_code=201)
async def upload_attachment(
    user: CurrentUser, db: DB, file: UploadFile = File(...), transaction_id: str | None = None
):
    if transaction_id:
        get_owned(db, Transaction, transaction_id, user.id, "Lançamento")
    data, mime = await _read_upload(file)
    a = _new_attachment(
        db, user.id, data, mime, _safe_name(file.filename, "arquivo"), transaction_id=transaction_id
    )
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
    if body.transaction_id:
        a.status = "confirmed"
    db.commit()
    return _attachment_out(a)


@router.get("/attachments")
def list_attachments(user: CurrentUser, db: DB, transaction_id: str):
    return [
        _attachment_out(a)
        for a in db.scalars(
            select(Attachment).where(
                Attachment.user_id == user.id,
                Attachment.transaction_id == transaction_id,
                Attachment.deleted_at.is_(None),
            )
        )
    ]


@router.get("/attachments/{attachment_id}/file")
@router.get("/documents/{attachment_id}/file")
def download_attachment(attachment_id: str, user: CurrentUser, db: DB):
    a = get_owned(db, Attachment, attachment_id, user.id, "Documento")
    return Response(
        storage.load(a),
        media_type=a.content_type,
        headers={
            "Content-Disposition": f'inline; filename="{_safe_name(a.filename, "documento")}"',
            # Nunca executa nada vindo do arquivo (PDF com script, SVG disfarçado etc.)
            "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox",
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.delete("/attachments/{attachment_id}", status_code=204)
def delete_attachment(attachment_id: str, user: CurrentUser, db: DB):
    delete_document(attachment_id, user, db)
