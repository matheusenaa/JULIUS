"""Leitura de comprovantes (foto/PDF) via IA multimodal → proposta de lançamento.

Sempre exige confirmação do usuário: OCR erra, principalmente em fotos ruins.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.nlp_pt import keyword_category
from app.ai.providers import AIUnavailable, get_provider
from app.ai.quick_input import _default_account, _find_category
from app.models import Account, Category, User
from app.services import categorizer
from app.services.categorizer import normalize

SYSTEM = """Você lê comprovantes brasileiros (cupom fiscal, nota fiscal, comprovante Pix, boleto pago,
comprovante bancário) e devolve SOMENTE JSON:
{"document_type": "cupom"|"nota_fiscal"|"pix"|"boleto"|"bancario"|"outro",
 "merchant": nome do estabelecimento ou favorecido (ou null),
 "date": "AAAA-MM-DD" ou null,
 "total": valor TOTAL pago impresso no documento, número em reais (ou null),
 "direction": "expense" se o usuário pagou, "income" se recebeu,
 "payment_method": "pix"|"debit"|"credit"|"cash"|"boleto"|"transfer"|null,
 "items": até 5 itens principais (textos curtos),
 "category_id": id da lista de categorias que melhor descreve a compra, ou null,
 "legible": true/false}
Copie o valor total exatamente como impresso. Não some itens. Se não conseguir ler, use null."""

MAGIC = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG": "image/png",
    b"%PDF": "application/pdf",
}


def sniff(data: bytes) -> str | None:
    for magic, mime in MAGIC.items():
        if data.startswith(magic):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def read_receipt(db: Session, user: User, data: bytes, mime: str, today: date) -> dict:
    provider = get_provider()
    if provider is None:
        raise AIUnavailable("Leitura de comprovantes precisa de um provedor de IA configurado.")
    cats = db.scalars(
        select(Category).where(Category.user_id == user.id, Category.deleted_at.is_(None))
    ).all()
    accounts = db.scalars(
        select(Account)
        .where(Account.user_id == user.id, Account.deleted_at.is_(None))
        .order_by(Account.created_at)
    ).all()
    prompt = f"Hoje: {today.isoformat()}\nCategorias (id | nome | tipo):\n" + "\n".join(
        f"{c.id} | {c.name} | {c.kind}" for c in cats
    )
    raw = provider.generate_json(SYSTEM, prompt, image=data, mime=mime)

    tx_type = "income" if raw.get("direction") == "income" else "expense"
    amount = None
    if isinstance(raw.get("total"), int | float) and 0 < raw["total"] < 10**10:
        amount = round(float(raw["total"]) * 100)
    occurred_on = today
    if isinstance(raw.get("date"), str):
        try:
            parsed = date.fromisoformat(raw["date"])
            if parsed.year >= 2000 and parsed <= today:
                occurred_on = parsed
        except ValueError:
            pass
    merchant = raw.get("merchant") if isinstance(raw.get("merchant"), str) else None
    items = [i for i in raw.get("items") or [] if isinstance(i, str)][:5]
    text = " ".join([merchant or "", *items])

    by_id = {c.id: c for c in cats}
    learned = by_id.get(categorizer.suggest_from_rules(db, user.id, text) or "")
    ai_cat = by_id.get(raw.get("category_id") or "")
    kw_cat = _find_category(cats, keyword_category(normalize(text)), tx_type)
    category = next((c for c in (learned, ai_cat, kw_cat) if c and c.kind == tx_type), None)
    payment = (
        raw.get("payment_method")
        if raw.get("payment_method") in ("pix", "debit", "credit", "cash", "boleto", "transfer")
        else None
    )
    account = _default_account(user, accounts, payment)

    missing = [f for f, v in (("amount_cents", amount), ("account_id", account)) if v is None]
    return {
        "type": tx_type,
        "amount_cents": amount,
        "occurred_on": occurred_on,
        "description": (merchant or (category.name if category else "Comprovante"))[:200],
        "category_id": category.id if category else None,
        "account_id": account.id if account else None,
        "to_account_id": None,
        "payment_method": "credit" if account and account.kind == "credit_card" else payment,
        "installments": 1,
        "status": "paid",
        "is_fixed": False,
        "recurrence": None,
        "notes": ("Itens: " + ", ".join(items)) if items else None,
        "engine": "ai",
        "legible": bool(raw.get("legible", True)),
        "document_type": raw.get("document_type"),
        "missing": missing,
        "raw": raw,
    }
