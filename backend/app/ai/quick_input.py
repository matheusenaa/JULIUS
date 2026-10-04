"""Quick Input: frase livre → PROPOSTA de lançamento. Nada é gravado aqui.

Ordem de confiança:
- Valor: sempre do parser determinístico; a IA só preenche se ele não achar nada.
- Categoria: correções do usuário > IA > dicionário de palavras-chave.
- Qualquer id devolvido pela IA é validado contra os dados reais do usuário.
"""

import logging
import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import nlp_pt
from app.ai.providers import AIUnavailable, get_provider
from app.models import Account, Category, User
from app.services import categorizer
from app.services.categorizer import normalize
from app.services.dates import local_today

log = logging.getLogger("julius.quick_input")

FIXED_BY_DEFAULT = {
    "Aluguel",
    "Condomínio",
    "Internet",
    "Energia",
    "Água",
    "Celular",
    "Plano de saúde",
    "Mensalidade",
    "Streaming",
    "Academia",
    "Aplicativos",
    "Salário",
    "Gás",
}

SYSTEM = """Você interpreta frases curtas em português sobre finanças pessoais e devolve SOMENTE JSON.
Campos: type ("income"|"expense"|"transfer"), amount (número em reais, ex.: 45.9, ou null),
date ("AAAA-MM-DD"), description (até 60 caracteres, sem o valor), category_id (um id da lista ou null),
account_id (id da lista ou null), to_account_id (id da lista, apenas transferências, ou null),
payment_method ("pix"|"debit"|"credit"|"cash"|"boleto"|"transfer"|"other"|null),
installments (inteiro, 1 se à vista), recurring (null|"weekly"|"monthly"|"yearly"), day_of_month (1-31 ou null).
Não invente valores: se a frase não tiver valor, use null. Não faça contas."""


def _context(db: Session, user_id: str):
    cats = db.scalars(
        select(Category).where(Category.user_id == user_id, Category.deleted_at.is_(None))
    ).all()
    accounts = db.scalars(
        select(Account)
        .where(Account.user_id == user_id, Account.deleted_at.is_(None))
        .order_by(Account.created_at)
    ).all()
    return cats, accounts


def _find_category(cats, name: str | None, kind: str) -> Category | None:
    if not name:
        return None
    target = normalize(name)
    matches = [c for c in cats if normalize(c.name) == target and c.kind == kind]
    # Prefere subcategoria (mais específica) quando o nome existe nos dois níveis
    matches.sort(key=lambda c: c.parent_id is None)
    return matches[0] if matches else None


def _mentioned_accounts(accounts, norm: str) -> list[tuple[int, Account]]:
    found = []
    for a in accounts:
        n = normalize(a.name)
        if len(n) >= 3:
            m = re.search(rf"\b{re.escape(n)}\b", norm)
            if m:
                found.append((m.start(), a))
    return sorted(found, key=lambda x: x[0])


def _default_account(user: User, accounts, payment: str | None) -> Account | None:
    cards = [a for a in accounts if a.kind == "credit_card"]
    if payment == "credit" and len(cards) == 1:
        return cards[0]
    preferred = (user.settings or {}).get("default_account_id")
    for a in accounts:
        if a.id == preferred:
            return a
    non_cards = [a for a in accounts if a.kind != "credit_card"]
    return (non_cards or accounts or [None])[0]


def _ask_ai(text: str, today: date, cats, accounts) -> dict | None:
    provider = get_provider()
    if provider is None:
        return None
    parents = {c.id: c.name for c in cats if c.parent_id is None}
    cat_lines = "\n".join(
        f"{c.id} | {c.name}{f' (em {parents.get(c.parent_id)})' if c.parent_id else ''} | {c.kind}"
        for c in cats
    )
    acc_lines = "\n".join(f"{a.id} | {a.name} | {a.kind}" for a in accounts)
    prompt = (
        f"Hoje é {today.isoformat()}.\nCategorias (id | nome | tipo):\n{cat_lines}\n\n"
        f'Contas (id | nome | tipo):\n{acc_lines}\n\nFrase: "{text}"'
    )
    try:
        return provider.generate_json(SYSTEM, prompt)
    except AIUnavailable:
        raise
    except Exception:  # noqa: BLE001 — IA nunca pode derrubar o lançamento
        log.exception("Falha inesperada na IA")
        raise AIUnavailable("erro inesperado") from None


def parse(db: Session, user: User, text: str, today: date | None = None) -> dict:
    today = today or local_today()
    cats, accounts = _context(db, user.id)
    cat_by_id = {c.id: c for c in cats}
    acc_by_id = {a.id: a for a in accounts}
    norm = normalize(text)
    local = nlp_pt.parse(text, today)

    tx_type = local.type
    amount = local.amount_cents
    occurred_on = local.occurred_on
    description = local.description
    payment = local.payment_method
    installments = local.installments
    recurrence = local.recurrence
    day_of_month = local.day_of_month
    engine = "local"
    ai_error = False

    learned_id = categorizer.suggest_from_rules(db, user.id, text)
    learned = cat_by_id.get(learned_id) if learned_id else None
    keyword_cat = _find_category(cats, local.category_name, "income" if tx_type == "income" else "expense")
    category = learned or keyword_cat

    mentioned = _mentioned_accounts(accounts, norm)
    account = mentioned[0][1] if mentioned else None
    to_account = None

    ai = None
    try:
        ai = _ask_ai(text, today, cats, accounts)
    except AIUnavailable:
        ai_error = True
    if ai:
        engine = "ai"
        if ai.get("type") in ("income", "expense", "transfer"):
            tx_type = ai["type"]
        if amount is None and isinstance(ai.get("amount"), int | float) and ai["amount"] > 0:
            amount = round(float(ai["amount"]) * 100)
        if isinstance(ai.get("date"), str):
            try:
                occurred_on = date.fromisoformat(ai["date"])
            except ValueError:
                pass
        if isinstance(ai.get("description"), str) and ai["description"].strip():
            description = ai["description"].strip()[:200]
        ai_cat = cat_by_id.get(ai.get("category_id"))
        if ai_cat and not learned:
            category = ai_cat
        if ai.get("account_id") in acc_by_id:
            account = acc_by_id[ai["account_id"]]
        if ai.get("to_account_id") in acc_by_id:
            to_account = acc_by_id[ai["to_account_id"]]
        if ai.get("payment_method") in ("pix", "debit", "credit", "cash", "boleto", "transfer", "other"):
            payment = ai["payment_method"]
        if isinstance(ai.get("installments"), int) and 1 <= ai["installments"] <= 120:
            installments = ai["installments"]
        if ai.get("recurring") in ("weekly", "monthly", "yearly", None):
            recurrence = ai.get("recurring") or recurrence
        if isinstance(ai.get("day_of_month"), int) and 1 <= ai["day_of_month"] <= 31:
            day_of_month = ai["day_of_month"]

    # Transferência: origem e destino
    if tx_type == "transfer":
        if to_account is None:
            dest_match = re.search(r"\b(para|pra|pro|na|no)\s+(?:a |o )?(\w[\w ]*)", norm)
            if nlp_pt.INVOICE_RX.search(norm):
                cards = [a for _, a in mentioned if a.kind == "credit_card"] or [
                    a for a in accounts if a.kind == "credit_card"
                ]
                to_account = cards[0] if cards else None
            elif dest_match:
                for _, a in mentioned:
                    if normalize(a.name) in dest_match.group(2):
                        to_account = a
                        break
        if account is None or account is to_account:
            others = [a for _, a in mentioned if a is not to_account]
            account = (
                others[0]
                if others
                else _default_account(
                    user, [a for a in accounts if a is not to_account and a.kind != "credit_card"], None
                )
            )
        category = None
        installments = 1
        payment = payment or "transfer"
    elif account is None:
        account = _default_account(user, accounts, payment)

    if category is not None and tx_type in ("income", "expense") and category.kind != tx_type:
        category = None
    if account is not None and account.kind == "credit_card" and tx_type == "expense":
        payment = "credit"
    if installments > 1 and tx_type != "expense":
        installments = 1

    if not description:
        description = category.name if category else ("Receita" if tx_type == "income" else "Despesa")

    future = occurred_on > today
    missing = [f for f, v in (("amount_cents", amount), ("account_id", account)) if v is None]
    if tx_type == "transfer" and to_account is None:
        missing.append("to_account_id")
    confidence = 0.4
    confidence += 0.3 if amount else 0
    confidence += 0.2 if category or tx_type == "transfer" else 0
    confidence += 0.1 if engine == "ai" else 0

    return {
        "text": text,
        "type": tx_type,
        "amount_cents": amount,
        "occurred_on": occurred_on,
        "description": description[:200],
        "category_id": category.id if category else None,
        "account_id": account.id if account else None,
        "to_account_id": to_account.id if to_account else None,
        "payment_method": payment,
        "installments": installments,
        "status": "pending" if future or local.future else "paid",
        "is_fixed": bool(recurrence) or (category is not None and category.name in FIXED_BY_DEFAULT),
        "recurrence": (
            {"frequency": recurrence, "day_of_month": day_of_month or occurred_on.day}
            if recurrence and tx_type != "transfer"
            else None
        ),
        "learned": learned is not None,
        "engine": engine,
        "ai_error": ai_error,
        "confidence": round(min(confidence, 1.0), 2),
        "missing": missing,
    }
