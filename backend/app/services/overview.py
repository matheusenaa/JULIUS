"""Visão geral: tudo que a tela de dashboard precisa, em uma única resposta.

Reaproveita a linha do tempo (forecast) e os cálculos existentes; aqui só se monta
a visão. Nenhum número é calculado no navegador.
"""

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import InstallmentPlan, Recurrence, Transaction
from app.services import analytics, ledger
from app.services import debts as debts_svc
from app.services import forecast as fc
from app.services.dates import month_end, month_start


def balance_history(db: Session, user_id: str, today: date, days: int) -> list[dict]:
    """Saldo disponível ao fim de cada dia nos últimos `days` dias (realizado)."""
    cash = ledger.cash_accounts(db, user_id)
    current = ledger.cash_balance(db, user_id, today)
    start = today - timedelta(days=days - 1)
    effect: dict[date, int] = defaultdict(int)
    rows = db.execute(
        select(
            Transaction.occurred_on,
            Transaction.type,
            Transaction.account_id,
            Transaction.to_account_id,
            Transaction.amount_cents,
        ).where(
            Transaction.user_id == user_id,
            Transaction.deleted_at.is_(None),
            Transaction.status == "paid",
            Transaction.occurred_on > start,
            Transaction.occurred_on <= today,
        )
    )
    for d, tx_type, acc, to_acc, cents in rows:
        if acc in cash:
            effect[d] += cents if tx_type == "income" else -cents
        if tx_type == "transfer" and to_acc in cash:
            effect[d] += cents
    points, balance = [], current
    d = today
    while d >= start:
        points.append({"date": d, "balance_cents": balance})
        balance -= effect[d]  # saldo no fim do dia anterior
        d -= timedelta(days=1)
    return list(reversed(points))


def installment_plans(db: Session, user_id: str, today: date) -> list[dict]:
    future = case((Transaction.occurred_on > today, Transaction.amount_cents), else_=0)
    rows = db.execute(
        select(
            InstallmentPlan,
            func.sum(case((Transaction.occurred_on > today, 1), else_=0)),
            func.coalesce(func.sum(future), 0),
            func.min(case((Transaction.occurred_on > today, Transaction.occurred_on), else_=None)),
        )
        .join(Transaction, Transaction.installment_plan_id == InstallmentPlan.id)
        .where(
            InstallmentPlan.user_id == user_id,
            InstallmentPlan.deleted_at.is_(None),
            Transaction.deleted_at.is_(None),
            Transaction.status != "canceled",
        )
        .group_by(InstallmentPlan.id)
    ).all()
    out = []
    for plan, remaining, remaining_cents, next_date in rows:
        if not remaining:
            continue
        out.append(
            {
                "id": plan.id,
                "description": plan.description,
                "account_id": plan.account_id,
                "total_cents": plan.total_cents,
                "installments": plan.installments,
                "remaining_installments": int(remaining),
                "remaining_cents": int(remaining_cents),
                "next_date": next_date,
            }
        )
    return sorted(out, key=lambda p: p["next_date"] or today)


def recurring_summary(db: Session, user_id: str, today: date) -> dict:
    recs = db.scalars(
        select(Recurrence).where(
            Recurrence.user_id == user_id,
            Recurrence.deleted_at.is_(None),
            (Recurrence.end_date.is_(None)) | (Recurrence.end_date >= today),
        )
    ).all()

    def monthly(r: Recurrence) -> int:
        return {
            "monthly": r.amount_cents,
            "weekly": r.amount_cents * 52 // 12,
            "yearly": r.amount_cents // 12,
        }[r.frequency]

    return {
        "monthly_in_cents": sum(monthly(r) for r in recs if r.type == "income"),
        "monthly_out_cents": sum(monthly(r) for r in recs if r.type == "expense"),
        "count": len(recs),
    }


def calendar(db: Session, user_id: str, today: date, month: date) -> list[dict]:
    """Um item por dia do mês: o que entrou/saiu (realizado) e o que está previsto."""
    start, end = month_start(month), month_end(month)
    days: dict[date, dict] = {}
    d = start
    while d <= end:
        days[d] = {"date": d, "in_cents": 0, "out_cents": 0, "events": []}
        d += timedelta(days=1)
    for d, tx_type, total in db.execute(
        select(Transaction.occurred_on, Transaction.type, func.sum(Transaction.amount_cents))
        .where(
            Transaction.user_id == user_id,
            Transaction.deleted_at.is_(None),
            Transaction.status == "paid",
            Transaction.type.in_(("income", "expense")),
            Transaction.occurred_on.between(start, min(end, today)),
        )
        .group_by(Transaction.occurred_on, Transaction.type)
    ):
        days[d]["in_cents" if tx_type == "income" else "out_cents"] += int(total)
    if end >= today:
        for e in fc.events(db, user_id, today, end):
            if e.status == "scheduled":
                continue
            day = days.get(e.effective)
            if day is not None:
                day["events"].append(
                    {
                        "description": e.description,
                        "amount_cents": e.amount_cents,
                        "flow": e.flow,
                        "status": e.status,
                        "kind": e.kind,
                    }
                )
    return list(days.values())


def build(
    db: Session, user_id: str, today: date, horizon_days: int = 30, cal_month: date | None = None
) -> dict:
    tl = fc.timeline(db, user_id, today, today + timedelta(days=horizon_days))
    month_tl = fc.timeline(db, user_id, today, month_end(today))
    start = month_start(today)
    totals = ledger.totals_by_type(db, user_id, start, month_end(today))
    debt_rows = debts_svc.statuses(db, user_id, today)
    plans = installment_plans(db, user_id, today)
    open_events = [e for e in tl["events"] if e.status != "scheduled"]
    return {
        "today": today,
        "horizon_days": horizon_days,
        "kpis": {
            "balance_cents": tl["start_balance_cents"],
            "month_income_cents": totals["income"],
            "month_expense_cents": totals["expense"],
            "projected_month_end_cents": month_tl["end_balance_cents"],
            "projected_horizon_cents": tl["end_balance_cents"],
            "to_pay_cents": sum(e.amount_cents for e in open_events if e.flow == "out"),
            "to_receive_cents": sum(e.amount_cents for e in open_events if e.flow == "in"),
            "overdue_count": sum(1 for e in open_events if e.status == "overdue"),
            "debts_remaining_cents": sum(s.remaining_cents for d, s in debt_rows if d.status == "active"),
            "installments_remaining_cents": sum(p["remaining_cents"] for p in plans),
        },
        "timeline": {
            "start_balance_cents": tl["start_balance_cents"],
            "end_balance_cents": tl["end_balance_cents"],
            "lowest": tl["lowest"],
            "events": [e.as_dict() for e in tl["events"]],
        },
        "projection": fc.daily_projection(tl),
        "history": balance_history(db, user_id, today, 90),
        "monthly": [
            {"month": m["month"], "income": m["income"], "expense": m["expense"]}
            for m in analytics.monthly_series(db, user_id, start, 6)
        ],
        "categories": analytics.expenses_by_category(db, user_id, start, month_end(today)),
        "calendar": calendar(db, user_id, today, cal_month or today),
        "debts": [
            {
                "id": d.id,
                "name": d.name,
                "creditor": d.creditor,
                "remaining_cents": s.remaining_cents,
                "remaining_installments": s.remaining_installments,
                "installments_total": d.installments_total,
                "next_due": s.next_due,
                "situation": s.situation,
            }
            for d, s in debt_rows
            if d.status == "active" and s.remaining_installments
        ],
        "installments": plans,
        "recurring": recurring_summary(db, user_id, today),
        "goals": analytics.goals_status(db, user_id, today),
        "alerts": analytics.insights(db, user_id, today),
    }
