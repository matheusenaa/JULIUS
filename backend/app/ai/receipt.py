"""Leitura de documentos (foto/PDF) → extração + PROPOSTA de lançamento.

Ordem de confiança:
1. Linha digitável de boleto válida (valor e vencimento exatos);
2. Texto do PDF interpretado por regras;
3. IA multimodal (fotos, ou para completar o que faltou).
Nada é gravado sem revisão do usuário: OCR erra, principalmente em fotos ruins.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import doc_parser
from app.ai.nlp_pt import keyword_category
from app.ai.providers import AIUnavailable, get_provider_for
from app.ai.quick_input import _default_account, _find_category
from app.models import Account, Category, User
from app.services import categorizer
from app.services.categorizer import normalize

SYSTEM = """Você lê documentos financeiros brasileiros (conta de luz/água/internet/telefone, boleto,
comprovante Pix, comprovante bancário, nota fiscal, cupom, recibo, fatura) e devolve SOMENTE JSON:
{"document_type": "conta"|"boleto"|"pix"|"bancario"|"nota_fiscal"|"cupom"|"recibo"|"fatura"|"outro",
 "title": nome curto do que é (ex.: "Internet Vivo", "Conta de luz"),
 "beneficiary": empresa/favorecido que recebe, ou null,
 "institution": banco/instituição, ou null,
 "total": valor TOTAL a pagar/pago impresso, número em reais, ou null,
 "issue_date": "AAAA-MM-DD" (emissão/pagamento) ou null,
 "due_date": "AAAA-MM-DD" (vencimento) ou null,
 "document_number": número do documento/nota, ou null,
 "barcode": linha digitável SÓ COM DÍGITOS, ou null,
 "pix_key": chave Pix, ou null,
 "direction": "expense" se o usuário paga, "income" se recebe,
 "payment_method": "pix"|"debit"|"credit"|"cash"|"boleto"|"transfer"|null,
 "category_id": id da lista que melhor descreve, ou null,
 "recurring": true se for conta mensal (luz, água, internet, telefone, aluguel, plano),
 "legible": true/false}
Copie valores exatamente como impressos. Não some itens. Se não conseguir ler, use null."""

KIND_MAP = {
    "conta": "bill",
    "boleto": "bill",
    "fatura": "bill",
    "pix": "pix",
    "bancario": "receipt",
    "nota_fiscal": "invoice",
    "cupom": "receipt",
    "recibo": "receipt",
    "outro": "other",
}

MAGIC = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG": "image/png",
    b"%PDF": "application/pdf",
}
EXTENSIONS = {
    "image/jpeg": (".jpg", ".jpeg"),
    "image/png": (".png",),
    "image/webp": (".webp",),
    "application/pdf": (".pdf",),
}


def sniff(data: bytes) -> str | None:
    for magic, mime in MAGIC.items():
        if data.startswith(magic):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _iso(value) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        d = date.fromisoformat(value[:10])
        return d if d.year >= 2000 else None
    except ValueError:
        return None


def _merge_ai(ex: doc_parser.Extraction, raw: dict, today: date) -> None:
    """A IA completa o que as regras não acharam; nunca sobrescreve um boleto válido."""
    ex.engine = "rules+ai" if ex.engine == "rules" and (ex.amount_cents or ex.barcode) else "ai"
    exact = ex.barcode_valid is True
    if ex.amount_cents is None and isinstance(raw.get("total"), int | float) and 0 < raw["total"] < 10**10:
        ex.amount_cents = round(float(raw["total"]) * 100)
    if not exact and not ex.due_date:
        ex.due_date = _iso(raw.get("due_date"))
    if not ex.issue_date:
        issued = _iso(raw.get("issue_date"))
        ex.issue_date = issued if issued and issued <= today else None
    # "merchant"/"date" são aceitos por compatibilidade com o formato anterior do prompt
    if not raw.get("title") and isinstance(raw.get("merchant"), str):
        raw = {**raw, "title": raw["merchant"]}
    if not raw.get("issue_date") and raw.get("date"):
        raw = {**raw, "issue_date": raw["date"]}
        if not ex.issue_date:
            issued = _iso(raw["issue_date"])
            ex.issue_date = issued if issued and issued <= today else None
    for attr, key in (
        ("title", "title"),
        ("beneficiary", "beneficiary"),
        ("institution", "institution"),
        ("document_number", "document_number"),
        ("pix_key", "pix_key"),
    ):
        if not getattr(ex, attr) and isinstance(raw.get(key), str) and raw[key].strip():
            setattr(ex, attr, raw[key].strip()[:120])
    if not ex.barcode and isinstance(raw.get("barcode"), str):
        decoded = doc_parser.decode_boleto(raw["barcode"], today)
        if decoded and decoded["valid"]:
            ex.barcode, ex.barcode_valid = decoded["barcode"], True
            ex.amount_cents = decoded["amount_cents"] or ex.amount_cents
            ex.due_date = decoded["due_date"] or ex.due_date
    if ex.kind == "other":
        ex.kind = KIND_MAP.get(raw.get("document_type"), "other")
    if raw.get("direction") == "income":
        ex.direction = "income"
    ex.recurring_hint = ex.recurring_hint or bool(raw.get("recurring"))
    if raw.get("legible") is False:
        ex.warnings.append("A imagem parece pouco legível: confira todos os campos.")


def analyze(db: Session, user: User, data: bytes, mime: str, today: date) -> tuple[dict, dict]:
    """Retorna (extração, proposta). Lança AIUnavailable só quando nada pôde ser lido."""
    ex = (
        doc_parser.parse_text(doc_parser.pdf_text(data), today)
        if mime == "application/pdf"
        else doc_parser.Extraction()
    )
    cats = db.scalars(
        select(Category).where(Category.user_id == user.id, Category.deleted_at.is_(None))
    ).all()
    accounts = db.scalars(
        select(Account)
        .where(Account.user_id == user.id, Account.deleted_at.is_(None))
        .order_by(Account.created_at)
    ).all()

    raw = None
    provider = get_provider_for(user)
    needs_ai = ex.amount_cents is None or not ex.title
    if provider is not None and needs_ai:
        prompt = f"Hoje: {today.isoformat()}\nCategorias (id | nome | tipo):\n" + "\n".join(
            f"{c.id} | {c.name} | {c.kind}" for c in cats
        )
        try:
            raw = provider.generate_json(SYSTEM, prompt, image=data, mime=mime)
            _merge_ai(ex, raw, today)
        except AIUnavailable:
            ex.warnings.append("A IA não respondeu; dados obtidos só pela leitura automática.")
    if ex.amount_cents is None and not ex.title and raw is None:
        if mime != "application/pdf":
            raise AIUnavailable(
                "Ler fotos precisa de um provedor de IA configurado. Preencha os dados manualmente."
            )
        raise AIUnavailable("Não encontrei informações legíveis neste PDF. Preencha os dados manualmente.")

    tx_type = "income" if ex.direction == "income" else "expense"
    text = " ".join(filter(None, [ex.title, ex.beneficiary, ex.institution]))
    by_id = {c.id: c for c in cats}
    learned = by_id.get(categorizer.suggest_from_rules(db, user.id, text) or "")
    ai_cat = by_id.get((raw or {}).get("category_id") or "")
    kw_cat = _find_category(cats, ex.category_name or keyword_category(normalize(text)), tx_type)
    category = next((c for c in (learned, ai_cat, kw_cat) if c and c.kind == tx_type), None)
    payment = (raw or {}).get("payment_method")
    if payment not in ("pix", "debit", "credit", "cash", "boleto", "transfer"):
        payment = "boleto" if ex.barcode else "pix" if ex.kind == "pix" else None
    account = _default_account(user, accounts, payment)

    # Conta a vencer → lançamento previsto na data do vencimento; senão, realizado
    future_bill = ex.due_date is not None and ex.due_date >= today and ex.kind in ("bill", "invoice", "other")
    occurred_on = ex.due_date if future_bill else (ex.issue_date or ex.due_date or today)
    if occurred_on > today and not future_bill:
        occurred_on = today
    notes = "; ".join(
        f"{label}: {value}"
        for label, value in (
            ("Linha digitável", ex.barcode),
            ("Nº do documento", ex.document_number),
            ("Chave Pix", ex.pix_key),
            ("Instituição", ex.institution),
        )
        if value
    )
    proposal = {
        "type": tx_type,
        "amount_cents": ex.amount_cents,
        "occurred_on": occurred_on,
        "description": (ex.title or ex.beneficiary or (category.name if category else "Documento"))[:200],
        "category_id": category.id if category else None,
        "account_id": account.id if account else None,
        "to_account_id": None,
        "payment_method": "credit" if account and account.kind == "credit_card" else payment,
        "installments": 1,
        "status": "pending" if future_bill else "paid",
        "is_fixed": ex.recurring_hint,
        "recurrence": (
            {"frequency": "monthly", "day_of_month": (ex.due_date or occurred_on).day}
            if ex.recurring_hint
            else None
        ),
        "notes": notes or None,
        "engine": ex.engine,
        "missing": [f for f, v in (("amount_cents", ex.amount_cents), ("account_id", account)) if v is None],
        "warnings": ex.warnings,
    }
    extraction = ex.as_dict()
    if raw is not None:
        extraction["ai_raw"] = raw
    return extraction, proposal


def read_receipt(db: Session, user: User, data: bytes, mime: str, today: date) -> dict:
    """Compatibilidade com /api/receipts/scan: devolve a proposta com a extração em "raw"."""
    extraction, proposal = analyze(db, user, data, mime, today)
    return {**proposal, "raw": extraction, "legible": not extraction.get("warnings")}
