"""Dashboard, relatórios e histórico de alterações."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.models import AuditLog
from app.schemas import AuditOut, TransactionOut
from app.services import analytics
from app.services.dates import local_today

router = APIRouter(prefix="/api", tags=["visão geral"])


@router.get("/dashboard")
def dashboard(user: CurrentUser, db: DB):
    data = analytics.dashboard(db, user.id, local_today())
    data["recent"] = [TransactionOut.model_validate(t) for t in data["recent"]]
    return data


@router.get("/reports")
def report(
    user: CurrentUser,
    db: DB,
    period: Literal["day", "week", "month", "year"] = "month",
    ref: date | None = None,
):
    return analytics.report(db, user.id, period, ref or local_today())


@router.get("/forecast")
def forecast(user: CurrentUser, db: DB, months: int = Query(default=6, ge=1, le=24)):
    return analytics.forecast(db, user.id, local_today(), months)


@router.get("/audit", response_model=list[AuditOut])
def audit_log(
    user: CurrentUser,
    db: DB,
    entity_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    q = select(AuditLog).where(AuditLog.user_id == user.id)
    if entity_id:
        q = q.where(AuditLog.entity_id == entity_id)
    return db.scalars(q.order_by(AuditLog.created_at.desc()).limit(limit)).all()
