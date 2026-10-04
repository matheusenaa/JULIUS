"""Cálculos de dashboard, relatórios e projeções.

Todos os números que a interface e o assistente mostram saem daqui.
"""

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Budget, Category, Goal, Transaction
from app.services import forecast as fc
from app.services import ledger
from app.services.dates import add_months, local_today, month_end, month_start, period_bounds, previous_period
from app.services.money import brl

UNCATEGORIZED = "Sem categoria"


_cards = ledger.cards


def current_balance(db: Session, user_id: str, today: date) -> int:
    return ledger.cash_balance(db, user_id, today)


def projected_balance(db: Session, user_id: str, today: date, until: date) -> dict:
    """Saldo estimado em `until`, a partir da linha do tempo (fonte única)."""
    tl = fc.timeline(db, user_id, today, until)
    by_kind: dict[str, int] = defaultdict(int)
    for e in tl["events"]:
        by_kind[e.kind] += e.signed
    return {
        "current_cents": tl["start_balance_cents"],
        "pending_cents": by_kind["transaction"],
        "recurring_cents": by_kind["recurrence"],
        "card_invoices_cents": -by_kind["invoice"],
        "debts_cents": -by_kind["debt"],
        "projected_cents": tl["end_balance_cents"],
        "until": until,
    }


def _category_maps(db: Session, user_id: str) -> tuple[dict[str, Category], dict[str, str]]:
    cats = {c.id: c for c in db.scalars(select(Category).where(Category.user_id == user_id))}
    top = {cid: (c.parent_id or cid) for cid, c in cats.items()}
    return cats, top


def expenses_by_category(
    db: Session, user_id: str, start: date, end: date, rollup: bool = True
) -> list[dict]:
    cats, top = _category_maps(db, user_id)
    totals: dict[str | None, int] = defaultdict(int)
    for cat_id, total in db.execute(
        select(Transaction.category_id, func.sum(Transaction.amount_cents))
        .where(
            Transaction.user_id == user_id,
            Transaction.deleted_at.is_(None),
            Transaction.status == "paid",
            Transaction.type == "expense",
            Transaction.occurred_on.between(start, end),
        )
        .group_by(Transaction.category_id)
    ):
        key = top.get(cat_id, cat_id) if rollup and cat_id else cat_id
        totals[key] += int(total)
    grand = sum(totals.values()) or 1
    result = []
    for cid, total in sorted(totals.items(), key=lambda kv: -kv[1]):
        cat = cats.get(cid) if cid else None
        result.append(
            {
                "category_id": cid,
                "name": cat.name if cat else UNCATEGORIZED,
                "color": cat.color if cat else None,
                "icon": cat.icon if cat else None,
                "total_cents": total,
                "share": round(total / grand, 4),
            }
        )
    return result


def fixed_variable(db: Session, user_id: str, start: date, end: date) -> dict:
    rows = db.execute(
        select(Transaction.is_fixed, func.sum(Transaction.amount_cents))
        .where(
            Transaction.user_id == user_id,
            Transaction.deleted_at.is_(None),
            Transaction.status == "paid",
            Transaction.type == "expense",
            Transaction.occurred_on.between(start, end),
        )
        .group_by(Transaction.is_fixed)
    ).all()
    d = {bool(k): int(v) for k, v in rows}
    return {"fixed_cents": d.get(True, 0), "variable_cents": d.get(False, 0)}


def upcoming(db: Session, user_id: str, today: date, days: int = 15) -> list[dict]:
    """Próximos compromissos (e atrasados), vindos da linha do tempo."""
    items = []
    for e in fc.events(db, user_id, today, today + timedelta(days=days)):
        if e.status == "scheduled":
            continue  # já realizado com data futura: não é algo "a pagar"
        items.append(
            {
                "kind": e.kind,
                "id": e.ref_id,
                "date": e.date,
                "type": "income" if e.flow == "in" else "expense",
                "description": e.description,
                "amount_cents": e.amount_cents,
                "overdue": e.status == "overdue",
                "status": e.status,
                "extra": e.extra,
            }
        )
    return sorted(items, key=lambda i: i["date"])


def budgets_status(db: Session, user_id: str, today: date) -> list[dict]:
    start, end = month_start(today), month_end(today)
    spent = {
        row["category_id"]: row["total_cents"]
        for row in expenses_by_category(db, user_id, start, end, rollup=True)
    }
    sub_spent = {
        row["category_id"]: row["total_cents"]
        for row in expenses_by_category(db, user_id, start, end, rollup=False)
    }
    result = []
    for b in db.scalars(select(Budget).where(Budget.user_id == user_id, Budget.deleted_at.is_(None))):
        cat = db.get(Category, b.category_id)
        if cat is None or cat.deleted_at is not None:
            continue
        used = spent.get(cat.id, 0) if cat.parent_id is None else sub_spent.get(cat.id, 0)
        result.append(
            {
                "id": b.id,
                "category_id": cat.id,
                "name": cat.name,
                "color": cat.color,
                "amount_cents": b.amount_cents,
                "spent_cents": used,
                "ratio": round(used / b.amount_cents, 4),
            }
        )
    return sorted(result, key=lambda r: -r["ratio"])


def goals_status(db: Session, user_id: str, today: date) -> list[dict]:
    balances = ledger.account_balances(db, user_id, as_of=today)
    result = []
    for g in db.scalars(
        select(Goal).where(Goal.user_id == user_id, Goal.deleted_at.is_(None)).order_by(Goal.created_at)
    ):
        progress = max(0, balances.get(g.account_id, 0)) if g.account_id else g.saved_cents
        monthly = None
        if g.target_date and g.target_date > today and progress < g.target_cents:
            months = max(1, (g.target_date.year - today.year) * 12 + g.target_date.month - today.month)
            monthly = -(-(g.target_cents - progress) // months)  # arredonda para cima
        result.append(
            {
                "id": g.id,
                "name": g.name,
                "target_cents": g.target_cents,
                "saved_cents": g.saved_cents,
                "target_date": g.target_date,
                "account_id": g.account_id,
                "progress_cents": progress,
                "monthly_needed_cents": monthly,
            }
        )
    return result


def monthly_series(db: Session, user_id: str, end_month: date, months: int) -> list[dict]:
    """Receitas e despesas realizadas mês a mês (para evolução e médias)."""
    series = []
    for i in range(months - 1, -1, -1):
        m = add_months(month_start(end_month), -i)
        totals = ledger.totals_by_type(db, user_id, m, month_end(m))
        series.append({"month": m, **totals, "net_cents": totals["income"] - totals["expense"]})
    return series


def averages(db: Session, user_id: str, today: date, months: int = 3) -> dict:
    """Média dos últimos N meses COMPLETOS. Só conta meses que têm algum lançamento."""
    last_full = add_months(month_start(today), -1)
    series = [m for m in monthly_series(db, user_id, last_full, months) if m["income"] or m["expense"]]
    n = len(series)
    if n == 0:
        return {"months_with_data": 0, "income_cents": None, "expense_cents": None, "net_cents": None}
    return {
        "months_with_data": n,
        "income_cents": sum(m["income"] for m in series) // n,
        "expense_cents": sum(m["expense"] for m in series) // n,
        "net_cents": sum(m["net_cents"] for m in series) // n,
    }


def forecast(db: Session, user_id: str, today: date, months_ahead: int = 6) -> dict:
    """ESTIMATIVA linear: saldo atual + média mensal líquida × meses. Não é garantia."""
    avg = averages(db, user_id, today)
    balance = current_balance(db, user_id, today)
    if avg["months_with_data"] == 0:
        return {
            "available": False,
            "reason": "Ainda não há um mês completo com lançamentos.",
            "current_cents": balance,
        }
    points = [
        {"month": add_months(month_start(today), i), "balance_cents": balance + avg["net_cents"] * i}
        for i in range(1, months_ahead + 1)
    ]
    return {
        "available": True,
        "is_estimate": True,
        "based_on_months": avg["months_with_data"],
        "avg_net_cents": avg["net_cents"],
        "current_cents": balance,
        "points": points,
    }


def report(db: Session, user_id: str, period: str, ref: date) -> dict:
    start, end = period_bounds(period, ref)
    prev_start, prev_end = period_bounds(period, previous_period(period, ref))
    totals = ledger.totals_by_type(db, user_id, start, end)
    prev = ledger.totals_by_type(db, user_id, prev_start, prev_end)
    cats = expenses_by_category(db, user_id, start, end)
    prev_cats = {
        c["category_id"]: c["total_cents"] for c in expenses_by_category(db, user_id, prev_start, prev_end)
    }
    for c in cats:
        c["previous_cents"] = prev_cats.get(c["category_id"], 0)

    top = [
        {
            "id": t.id,
            "date": t.occurred_on,
            "description": t.description,
            "amount_cents": t.amount_cents,
            "category_id": t.category_id,
        }
        for t in db.scalars(
            select(Transaction)
            .where(
                Transaction.user_id == user_id,
                Transaction.deleted_at.is_(None),
                Transaction.status == "paid",
                Transaction.type == "expense",
                Transaction.occurred_on.between(start, end),
            )
            .order_by(Transaction.amount_cents.desc())
            .limit(10)
        )
    ]

    if period == "year":
        series = [
            {"label": m["month"].isoformat(), "income": m["income"], "expense": m["expense"]}
            for m in monthly_series(db, user_id, date(ref.year, 12, 1), 12)
        ]
    else:
        daily: dict[date, dict[str, int]] = defaultdict(lambda: {"income": 0, "expense": 0})
        for d, tx_type, total in db.execute(
            select(Transaction.occurred_on, Transaction.type, func.sum(Transaction.amount_cents))
            .where(
                Transaction.user_id == user_id,
                Transaction.deleted_at.is_(None),
                Transaction.status == "paid",
                Transaction.type.in_(("income", "expense")),
                Transaction.occurred_on.between(start, end),
            )
            .group_by(Transaction.occurred_on, Transaction.type)
        ):
            daily[d][tx_type] = int(total)
        series = []
        d = start
        while d <= end:
            series.append({"label": d.isoformat(), **daily[d]})
            d += timedelta(days=1)

    net = totals["income"] - totals["expense"]
    return {
        "period": period,
        "start": start,
        "end": end,
        "income_cents": totals["income"],
        "expense_cents": totals["expense"],
        "net_cents": net,
        "savings_rate": round(net / totals["income"], 4) if totals["income"] else None,
        "previous": {
            "start": prev_start,
            "end": prev_end,
            "income_cents": prev["income"],
            "expense_cents": prev["expense"],
            "net_cents": prev["income"] - prev["expense"],
        },
        "by_category": cats,
        **fixed_variable(db, user_id, start, end),
        "top_expenses": top,
        "series": series,
        "forecast": forecast(db, user_id, local_today()),
    }


def insights(db: Session, user_id: str, today: date) -> list[dict]:
    """Alertas objetivos baseados em regras (sem IA)."""
    out: list[dict] = []
    for b in budgets_status(db, user_id, today):
        if b["ratio"] >= 1:
            out.append({"level": "danger", "text": f"Orçamento de {b['name']} estourado este mês."})
        elif b["ratio"] >= 0.8:
            out.append(
                {
                    "level": "warning",
                    "text": f"Você já usou {round(b['ratio'] * 100)}% do orçamento de {b['name']}.",
                }
            )

    # Categorias que cresceram bem acima da média dos 3 meses anteriores
    start = month_start(today)
    current = {c["category_id"]: c for c in expenses_by_category(db, user_id, start, today)}
    base: dict[str | None, int] = defaultdict(int)
    months_with_data = 0
    for i in range(1, 4):
        m = add_months(start, -i)
        rows = expenses_by_category(db, user_id, m, month_end(m))
        months_with_data += bool(rows)
        for c in rows:
            base[c["category_id"]] += c["total_cents"]
    if months_with_data:
        for cid, c in current.items():
            avg = base.get(cid, 0) / months_with_data
            if avg >= 5000 and c["total_cents"] > avg * 1.3:
                out.append(
                    {
                        "level": "info",
                        "text": f"{c['name']}: gasto do mês já está {round((c['total_cents'] / avg - 1) * 100)}% acima da sua média.",
                    }
                )

    # Mesmo mês até hoje × mesmo período do mês passado (ex.: "lazer aumentou 32%")
    prev_start = add_months(start, -1)
    prev_end = min(month_end(prev_start), prev_start.replace(day=1) + (today - start))
    previous = {
        c["category_id"]: c["total_cents"] for c in expenses_by_category(db, user_id, prev_start, prev_end)
    }
    for cid, c in current.items():
        before = previous.get(cid, 0)
        if before >= 5000 and c["total_cents"] >= before * 1.2 and c["total_cents"] - before >= 5000:
            pct = round((c["total_cents"] / before - 1) * 100)
            text = f"Seu gasto com {c['name'].lower()} aumentou {pct}% em relação ao mesmo período do mês passado."
            if not any(c["name"] in o["text"] for o in out):
                out.append({"level": "info", "text": text})

    # Compromissos: atrasados, hoje, amanhã, próximos 7 dias e saldo negativo projetado
    week = fc.timeline(db, user_id, today, today + timedelta(days=7))
    open_events = [e for e in week["events"] if e.status != "scheduled"]
    overdue = [e for e in open_events if e.status == "overdue"]
    if overdue:
        out.append(
            {
                "level": "warning",
                "text": f"{len(overdue)} compromisso(s) com data vencida aguardando confirmação.",
            }
        )
    for e in open_events:
        if e.status == "overdue":
            continue
        verb = "entra" if e.flow == "in" else "vence"
        if e.date == today:
            out.append({"level": "warning", "text": f"{e.description}: {verb} hoje ({brl(e.amount_cents)})."})
        elif e.date == today + timedelta(days=1):
            out.append({"level": "info", "text": f"{e.description}: {verb} amanhã ({brl(e.amount_cents)})."})
    to_pay = sum(e.amount_cents for e in open_events if e.flow == "out")
    if to_pay:
        out.append(
            {"level": "info", "text": f"Você tem {brl(to_pay)} em contas previstas para os próximos 7 dias."}
        )
    month_tl = fc.timeline(db, user_id, today, today + timedelta(days=30))
    if month_tl["lowest"]["balance_cents"] < 0 <= month_tl["start_balance_cents"]:
        when = month_tl["lowest"]["date"].strftime("%d/%m")
        out.append(
            {
                "level": "danger",
                "text": f"Pela projeção, seu saldo fica negativo em {when} ({brl(month_tl['lowest']['balance_cents'])}).",
            }
        )

    uncategorized = db.scalar(
        select(func.count())
        .select_from(Transaction)
        .where(
            Transaction.user_id == user_id,
            Transaction.deleted_at.is_(None),
            Transaction.type != "transfer",
            Transaction.category_id.is_(None),
        )
    )
    if uncategorized:
        out.append({"level": "info", "text": f"{uncategorized} lançamento(s) sem categoria."})
    return out


def dashboard(db: Session, user_id: str, today: date) -> dict:
    start, end = month_start(today), month_end(today)
    totals = ledger.totals_by_type(db, user_id, start, end)
    recent = db.scalars(
        select(Transaction)
        .where(Transaction.user_id == user_id, Transaction.deleted_at.is_(None))
        .order_by(Transaction.occurred_on.desc(), Transaction.created_at.desc())
        .limit(8)
    ).all()
    cards = []
    for card in _cards(db, user_id):
        invoices = [i for i in ledger.card_invoices(db, card) if i["remaining_cents"] > 0]
        cards.append(
            {
                "id": card.id,
                "name": card.name,
                "open_cents": sum(i["remaining_cents"] for i in invoices),
                "next_due": invoices[0]["due_date"] if invoices else None,
            }
        )
    return {
        "today": today,
        "balance_cents": current_balance(db, user_id, today),
        "month": {
            "start": start,
            "end": end,
            "income_cents": totals["income"],
            "expense_cents": totals["expense"],
            **fixed_variable(db, user_id, start, end),
        },
        "projection": projected_balance(db, user_id, today, end),
        "upcoming": upcoming(db, user_id, today),
        "recent": recent,
        "categories": expenses_by_category(db, user_id, start, end),
        "budgets": budgets_status(db, user_id, today),
        "goals": goals_status(db, user_id, today),
        "cards": cards,
        "insights": insights(db, user_id, today),
    }
