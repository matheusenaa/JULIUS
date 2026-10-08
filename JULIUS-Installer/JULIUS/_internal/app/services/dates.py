import calendar
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import get_settings


def local_today() -> date:
    """'Hoje' no fuso do usuário — nunca o do servidor (na nuvem ele roda em UTC)."""
    tz = get_settings().timezone
    if tz == "local":
        return date.today()
    return datetime.now(ZoneInfo(tz)).date()


def month_start(d: date) -> date:
    return d.replace(day=1)


def month_end(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def add_months(d: date, months: int, day: int | None = None) -> date:
    """Soma meses preservando o dia desejado; 31/jan + 1 mês = 28 ou 29/fev."""
    total = d.year * 12 + (d.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day or d.day, last))


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def period_bounds(period: str, ref: date) -> tuple[date, date]:
    """Início e fim (inclusivos) do período que contém `ref`."""
    if period == "day":
        return ref, ref
    if period == "week":
        start = week_start(ref)
        return start, start + timedelta(days=6)
    if period == "month":
        return month_start(ref), month_end(ref)
    if period == "year":
        return date(ref.year, 1, 1), date(ref.year, 12, 31)
    raise ValueError(f"período inválido: {period}")


def previous_period(period: str, ref: date) -> date:
    start, _ = period_bounds(period, ref)
    if period == "month":
        return add_months(start, -1)
    if period == "year":
        return date(start.year - 1, 1, 1)
    return start - timedelta(days=1)


MONTHS_PT = [
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
]
