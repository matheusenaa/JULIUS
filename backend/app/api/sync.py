from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser
from app.errors import AppError
from app.models import SyncConflict, SyncState
from app.services import audit
from app.services import sync as svc
from app.services.ownership import get_owned
from app.services.sync_client import SyncClient, SyncError, parse_cursor

router = APIRouter(prefix="/api/sync", tags=["sincronização"])


# ---------- Protocolo (usado por outros dispositivos) ----------
@router.get("/pull")
def pull(user: CurrentUser, db: DB, since: str | None = None):
    return svc.pull(db, user, parse_cursor(since))


class PushIn(BaseModel):
    changes: list[dict] = Field(max_length=5000)


@router.post("/push")
def push(body: PushIn, user: CurrentUser, db: DB):
    return {"results": svc.push(db, user, body.changes)}


# ---------- Esta instalação ↔ servidor online ----------
def _pending(db, user_id: str) -> int:
    total = 0
    for _, model in svc.ENTITIES:
        total += (
            db.scalar(
                select(func.count())
                .select_from(model)
                .where(
                    model.user_id == user_id,
                    (model.synced_version.is_(None)) | (model.version != model.synced_version),
                )
            )
            or 0
        )
    return total


def _conflict_out(c: SyncConflict) -> dict:
    return {
        "id": c.id,
        "entity": c.entity,
        "entity_id": c.entity_id,
        "local": c.local_data,
        "remote": c.remote_data,
        "created_at": c.created_at,
    }


@router.get("/status")
def status(user: CurrentUser, db: DB):
    state = db.scalar(select(SyncState).where(SyncState.user_id == user.id))
    conflicts = db.scalars(
        select(SyncConflict).where(SyncConflict.user_id == user.id, SyncConflict.resolved_at.is_(None))
    ).all()
    return {
        "linked": state is not None and bool(state.remote_token),
        "remote_url": state.remote_url if state else None,
        "remote_email": state.remote_email if state else None,
        "last_sync_at": state.last_sync_at if state else None,
        "last_error": state.last_error if state else None,
        "pending": _pending(db, user.id) if state else 0,
        "conflicts": [_conflict_out(c) for c in conflicts],
    }


class LinkIn(BaseModel):
    remote_url: HttpUrl
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


@router.post("/link")
def link(body: LinkIn, user: CurrentUser, db: DB):
    """Vincula esta instalação a uma conta no servidor online e faz a primeira sincronização."""
    try:
        result = SyncClient(db, user).link(str(body.remote_url), body.email, body.password)
    except SyncError as exc:
        raise AppError(400, "sync_failed", str(exc)) from exc
    audit.record(db, user.id, "sync", None, "link", f"Instalação vinculada a {body.remote_url}.")
    db.commit()
    return result


@router.post("/run")
def run(user: CurrentUser, db: DB):
    try:
        return SyncClient(db, user).sync()
    except SyncError as exc:
        raise AppError(400, "sync_failed", str(exc)) from exc


@router.post("/unlink", status_code=204)
def unlink(user: CurrentUser, db: DB):
    state = db.scalar(select(SyncState).where(SyncState.user_id == user.id))
    if state:
        db.delete(state)
        audit.record(db, user.id, "sync", None, "unlink", "Vínculo com o servidor online removido.")
        db.commit()


class ResolveIn(BaseModel):
    choice: Literal["local", "remote"]


@router.post("/conflicts/{conflict_id}/resolve")
def resolve(conflict_id: str, body: ResolveIn, user: CurrentUser, db: DB):
    conflict = get_owned(db, SyncConflict, conflict_id, user.id, "Conflito")
    if conflict.resolved_at:
        raise AppError(409, "already_resolved", "Este conflito já foi resolvido.")
    SyncClient(db, user).resolve(conflict, body.choice)
    label = "deste dispositivo" if body.choice == "local" else "do servidor"
    audit.record(
        db, user.id, "sync", conflict.entity_id, "resolve", f"Conflito resolvido mantendo a versão {label}."
    )
    db.commit()
    return {"resolved": True}
