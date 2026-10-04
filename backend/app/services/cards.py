"""Regras de cartão de crédito: em qual fatura cai uma compra e quando ela vence.

Convenção: compras feitas ANTES do dia de fechamento entram na fatura que fecha
naquele mês; compras no dia do fechamento ou depois vão para a fatura seguinte.
A fatura é identificada pelo mês em que fecha (`invoice_month` = dia 1 desse mês).
"""

import calendar
from datetime import date

from app.services.dates import add_months, month_start


def _clamped(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def invoice_month_for(purchase: date, closing_day: int) -> date:
    closing_this_month = _clamped(purchase.year, purchase.month, closing_day)
    if purchase < closing_this_month:
        return month_start(purchase)
    return add_months(month_start(purchase), 1)


def closing_date(invoice_month: date, closing_day: int) -> date:
    return _clamped(invoice_month.year, invoice_month.month, closing_day)


def due_date(invoice_month: date, closing_day: int, due_day: int) -> date:
    """Vencimento: no mesmo mês do fechamento se o dia for posterior; senão no mês seguinte."""
    base = invoice_month if due_day > closing_day else add_months(invoice_month, 1)
    return _clamped(base.year, base.month, due_day)


def split_installments(total_cents: int, n: int) -> list[int]:
    """Divide em n parcelas exatas; os centavos que sobram vão para a 1ª parcela.

    R$ 100,00 em 3x → [3334, 3333, 3333]. A soma é sempre igual ao total.
    """
    if n < 1 or total_cents <= 0:
        raise ValueError("parcelamento inválido")
    base, rest = divmod(total_cents, n)
    return [base + rest] + [base] * (n - 1)
