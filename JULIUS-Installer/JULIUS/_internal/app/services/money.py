"""Formatação de valores para textos gerados no servidor (assistente, alertas, histórico).

A moeda vem da preferência do usuário e é definida por requisição (contextvar),
para não precisar passar o usuário a cada chamada. O JULIUS não converte moedas:
cada usuário trabalha em uma moeda só.
"""

from contextvars import ContextVar

CURRENCIES = {"BRL": ("R$ ", ".", ","), "USD": ("US$ ", ",", "."), "EUR": ("€ ", ".", ",")}
current_currency: ContextVar[str] = ContextVar("current_currency", default="BRL")


def brl(cents: int, currency: str | None = None) -> str:
    """Formata centavos na moeda do usuário (o nome é histórico: o padrão é BRL)."""
    symbol, thousands, decimal = CURRENCIES.get(currency or current_currency.get(), CURRENCIES["BRL"])
    s = f"{abs(cents) / 100:,.2f}".replace(",", "X").replace(".", decimal).replace("X", thousands)
    return f"{'-' if cents < 0 else ''}{symbol}{s}"
