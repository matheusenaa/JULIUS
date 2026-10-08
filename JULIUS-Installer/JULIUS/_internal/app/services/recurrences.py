"""Recorrências: previsões virtuais + efetivação sem duplicidade.

Uma previsão só existe enquanto não há transação com o mesmo
(recurrence_id, occurrence_date). Transações excluídas também contam:
excluir a ocorrência de um mês equivale a "pular" aquele mês.
"""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Recurrence, Transaction
from app.services.dates import add_months


@dataclass(frozen=True)
class Occurrence:
    recurrence: Recurrence
    date: date


def occurrence_dates(rec: Recurrence, start: date, end: date) -> list[date]:
    last = min(end, rec.end_date) if rec.end_date else end
    dates: list[date] = []
    if last < rec.start_date:
        return dates
    if rec.frequency == "weekly":
        d = rec.start_date
        if d < start:
            d += timedelta(days=((start - d).days + 6) // 7 * 7)
        while d <= last:
            dates.append(d)
            d += timedelta(days=7)
        return dates

    step = 12 if rec.frequency == "yearly" else 1
    day = rec.day_of_month or rec.start_date.day
    i = 0
    while True:
        d = add_months(rec.start_date.replace(day=1), i * step, day)
        if d > last:
            break
        if d >= start and d >= rec.start_date:
            dates.append(d)
        i += 1
    return dates


def pending_occurrences(db: Session, user_id: str, start: date, end: date) -> list[Occurrence]:
    recs = db.scalars(
        select(Recurrence).where(
            Recurrence.user_id == user_id,
            Recurrence.deleted_at.is_(None),
            Recurrence.start_date <= end,
        )
    ).all()
    if not recs:
        return []
    done = {
        (rid, d)
        for rid, d in db.execute(
            select(Transaction.recurrence_id, Transaction.occurrence_date).where(
                Transaction.user_id == user_id,
                Transaction.recurrence_id.in_([r.id for r in recs]),
                Transaction.occurrence_date.between(start, end),
            )
        )
    }
    result = [
        Occurrence(rec, d)
        for rec in recs
        for d in occurrence_dates(rec, start, end)
        if (rec.id, d) not in done
    ]
    return sorted(result, key=lambda o: o.date)
