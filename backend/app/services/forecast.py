"""Linha do tempo financeira: "como estará meu dinheiro nos próximos dias?".

Fonte ÚNICA para projeção de saldo, próximos vencimentos, calendário, alertas e
assistente. Cada compromisso vira um evento com data, valor e o saldo depois dele.

Entram (apenas o que afeta o dinheiro disponível — contas fora do cartão):
- lançamentos previstos/confirmados (inclusive atrasados) e realizados com data futura;
- ocorrências de recorrências ainda não lançadas;
- faturas de cartão em aberto (as compras no cartão entram pela fatura, não individualmente);
- parcelas de dívidas ainda não pagas.

Itens atrasados entram na projeção "hoje": ainda precisam acontecer.
"""

from dataclasses import asdict, dataclass, field, replace
from datetime import date, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Transaction
from app.models.finance import OPEN_STATUSES
from app.services import debts as debts_svc
from app.services import ledger
from app.services.recurrences import pending_occurrences
from app.services.reqcache import cached

LOOKBACK_DAYS = 62  # até quando um item atrasado continua aparecendo


@dataclass
class Event:
    date: date
    effective: date
    kind: str  # transaction | recurrence | invoice | debt
    flow: str  # in | out
    amount_cents: int
    description: str
    status: str  # pending | confirmed | overdue | scheduled
    ref_id: str
    account_id: str | None = None
    category_id: str | None = None
    extra: dict = field(default_factory=dict)
    balance_after: int = 0

    @property
    def signed(self) -> int:
        return self.amount_cents if self.flow == "in" else -self.amount_cents

    def as_dict(self) -> dict:
        return asdict(self)


def _status(base: str, when: date, today: date) -> str:
    return "overdue" if when < today else base


def events(db: Session, user_id: str, today: date, until: date) -> list[Event]:
    # Cópias: timeline() escreve balance_after em cada evento
    return [
        replace(e)
        for e in cached(db, ("events", user_id, today, until), lambda: _events(db, user_id, today, until))
    ]


def _events(db: Session, user_id: str, today: date, until: date) -> list[Event]:
    cash = ledger.cash_accounts(db, user_id)
    card_ids = {c.id for c in ledger.cards(db, user_id)}
    out: list[Event] = []

    # 1. Lançamentos em aberto (qualquer data até `until`) e realizados com data futura
    txs = db.scalars(
        select(Transaction).where(
            Transaction.user_id == user_id,
            Transaction.deleted_at.is_(None),
            Transaction.occurred_on <= until,
            or_(
                Transaction.status.in_(OPEN_STATUSES),
                (Transaction.status == "paid") & (Transaction.occurred_on > today),
            ),
            Transaction.occurred_on >= today - timedelta(days=365),
        )
    )
    for tx in txs:
        if tx.type == "transfer":
            from_cash, to_cash = tx.account_id in cash, tx.to_account_id in cash
            if tx.to_account_id in card_ids or from_cash == to_cash:
                continue  # pagamento de fatura (coberto pela fatura) ou movimento neutro
            flow = "in" if to_cash else "out"
        elif tx.account_id not in cash:
            continue  # compra no cartão: entra pela fatura
        else:
            flow = "in" if tx.type == "income" else "out"
        base = "scheduled" if tx.status == "paid" else tx.status
        out.append(
            Event(
                date=tx.occurred_on,
                effective=max(tx.occurred_on, today),
                kind="transaction",
                flow=flow,
                amount_cents=tx.amount_cents,
                description=tx.description,
                status=_status(base, tx.occurred_on, today) if base != "scheduled" else base,
                ref_id=tx.id,
                account_id=tx.account_id,
                category_id=tx.category_id,
                extra={"version": tx.version, "installment": tx.installment_number, "debt_id": tx.debt_id},
            )
        )

    # 2. Recorrências ainda não lançadas
    for occ in pending_occurrences(db, user_id, today - timedelta(days=LOOKBACK_DAYS), until):
        r = occ.recurrence
        if r.account_id not in cash:
            continue
        out.append(
            Event(
                date=occ.date,
                effective=max(occ.date, today),
                kind="recurrence",
                flow="in" if r.type == "income" else "out",
                amount_cents=r.amount_cents,
                description=r.description,
                status=_status("pending", occ.date, today),
                ref_id=r.id,
                account_id=r.account_id,
                category_id=r.category_id,
                extra={"occurrence_date": occ.date.isoformat(), "frequency": r.frequency},
            )
        )

    # 3. Faturas de cartão em aberto
    for card in ledger.cards(db, user_id):
        for inv in ledger.card_invoices(db, card):
            if inv["remaining_cents"] <= 0 or inv["due_date"] > until:
                continue
            out.append(
                Event(
                    date=inv["due_date"],
                    effective=max(inv["due_date"], today),
                    kind="invoice",
                    flow="out",
                    amount_cents=inv["remaining_cents"],
                    description=f"Fatura {card.name}",
                    status=_status("pending", inv["due_date"], today),
                    ref_id=card.id,
                    account_id=card.id,
                    extra={
                        "invoice_month": inv["invoice_month"].isoformat(),
                        "total_cents": inv["total_cents"],
                    },
                )
            )

    # 4. Parcelas de dívidas
    for debt, due, number in debts_svc.upcoming_installments(db, user_id, until, today):
        if debt.account_id and debt.account_id not in cash:
            continue
        out.append(
            Event(
                date=due,
                effective=max(due, today),
                kind="debt",
                flow="out",
                amount_cents=debt.installment_cents,
                description=f"{debt.name} ({number}/{debt.installments_total})",
                status=_status("pending", due, today),
                ref_id=debt.id,
                account_id=debt.account_id,
                category_id=debt.category_id,
                extra={"installment": number},
            )
        )

    # Mesmo dia: entradas antes das saídas
    out.sort(key=lambda e: (e.effective, e.flow != "in", e.date, -e.amount_cents))
    return out


def timeline(db: Session, user_id: str, today: date, until: date) -> dict:
    start = ledger.cash_balance(db, user_id, today)
    evs = events(db, user_id, today, until)
    balance = start
    lowest = {"date": today, "balance_cents": start}
    for e in evs:
        balance += e.signed
        e.balance_after = balance
        if balance < lowest["balance_cents"]:
            lowest = {"date": e.effective, "balance_cents": balance}
    return {
        "today": today,
        "until": until,
        "start_balance_cents": start,
        "end_balance_cents": balance,
        "income_cents": sum(e.amount_cents for e in evs if e.flow == "in"),
        "expense_cents": sum(e.amount_cents for e in evs if e.flow == "out"),
        "lowest": lowest,
        "events": evs,
    }


def daily_projection(tl: dict) -> list[dict]:
    """Saldo projetado ao fim de cada dia (para o gráfico)."""
    by_day: dict[date, int] = {}
    for e in tl["events"]:
        by_day[e.effective] = e.balance_after
    points, balance = [], tl["start_balance_cents"]
    d = tl["today"]
    while d <= tl["until"]:
        balance = by_day.get(d, balance)
        points.append({"date": d, "balance_cents": balance})
        d += timedelta(days=1)
    return points
