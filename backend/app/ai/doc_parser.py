"""Leitura de documentos SEM IA: texto de PDF + regras + linha digitável de boleto.

A linha digitável do boleto carrega valor e vencimento codificados (padrão FEBRABAN),
com dígitos verificadores — quando ela é encontrada e é válida, valor e vencimento
são exatos, não estimados.
"""

import io
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from app.ai.nlp_pt import keyword_category, parse_number
from app.services.categorizer import normalize

log = logging.getLogger("julius.docs")

BANKS = {
    "001": "Banco do Brasil",
    "033": "Santander",
    "104": "Caixa",
    "237": "Bradesco",
    "341": "Itaú",
    "260": "Nubank",
    "077": "Banco Inter",
    "336": "C6 Bank",
    "212": "Banco Original",
    "756": "Sicoob",
    "748": "Sicredi",
    "041": "Banrisul",
    "290": "PagBank",
    "380": "PicPay",
    "323": "Mercado Pago",
}
INSTITUTIONS = [
    "Banco do Brasil",
    "Santander",
    "Caixa",
    "Bradesco",
    "Itaú",
    "Itau",
    "Nubank",
    "Inter",
    "C6",
    "Sicoob",
    "Sicredi",
    "PagBank",
    "PicPay",
    "Mercado Pago",
    "Neoenergia",
    "Enel",
    "Cemig",
    "Copel",
    "Sabesp",
    "Vivo",
    "Claro",
    "TIM",
    "Oi",
]


@dataclass
class Extraction:
    engine: str = "rules"
    title: str | None = None
    kind: str = "other"
    amount_cents: int | None = None
    issue_date: date | None = None
    due_date: date | None = None
    beneficiary: str | None = None
    institution: str | None = None
    document_number: str | None = None
    barcode: str | None = None
    barcode_valid: bool | None = None
    pix_key: str | None = None
    category_name: str | None = None
    recurring_hint: bool = False
    direction: str = "expense"
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        data = asdict(self)
        for k in ("issue_date", "due_date"):
            if data[k]:
                data[k] = data[k].isoformat()
        return data


def pdf_text(data: bytes, max_pages: int = 5) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages[:max_pages])
    except Exception:  # noqa: BLE001 — PDF corrompido/criptografado: segue sem texto
        log.info("Não foi possível extrair texto do PDF")
        return ""


def _mod10(digits: str) -> int:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch) * (2 if i % 2 == 0 else 1)
        total += n // 10 + n % 10
    return (10 - total % 10) % 10


def _due_from_factor(factor: int, today: date) -> date | None:
    if factor == 0:
        return None
    candidates = [date(1997, 10, 7) + timedelta(days=factor)]
    if factor >= 1000:  # o fator recomeçou em 22/02/2025 (FEBRABAN)
        candidates.append(date(2025, 2, 22) + timedelta(days=factor - 1000))
    return min(candidates, key=lambda d: abs((d - today).days))


def decode_boleto(line: str, today: date) -> dict | None:
    """Linha digitável de boleto bancário (47) ou de concessionária (48)."""
    digits = re.sub(r"\D", "", line)
    if len(digits) == 47:
        fields = [(digits[0:9], digits[9]), (digits[10:20], digits[20]), (digits[21:31], digits[31])]
        valid = all(_mod10(body) == int(dv) for body, dv in fields)
        factor, value = int(digits[33:37]), int(digits[37:47])
        return {
            "barcode": digits,
            "valid": valid,
            "amount_cents": value or None,
            "due_date": _due_from_factor(factor, today),
            "institution": BANKS.get(digits[0:3]),
            "type": "bancario",
        }
    if len(digits) == 48 and digits[0] == "8":
        blocks = [digits[i : i + 12] for i in range(0, 48, 12)]
        value_id = digits[2]
        valid = None
        if value_id in "67":
            valid = all(_mod10(b[:11]) == int(b[11]) for b in blocks)
        code = "".join(b[:11] for b in blocks)
        value = int(code[4:15]) if value_id in "68" else 0
        return {
            "barcode": digits,
            "valid": valid,
            "amount_cents": value or None,
            "due_date": None,
            "institution": None,
            "type": "concessionaria",
        }
    return None


_DATE = r"(\d{2})[/.-](\d{2})[/.-](\d{2,4})"
_MONEY = r"(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*,\d{2})"
# Só pontos e espaços entre os dígitos: \s atravessaria quebras de linha e juntaria
# números de linhas vizinhas (ex.: o ano da data de vencimento) à linha digitável
LINE_RX = re.compile(r"(?<![\d.])(?:\d[\d. ]{45,60}\d)(?![\d.])")


def _to_date(m: re.Match) -> date | None:
    d, mth, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    y = y + 2000 if y < 100 else y
    try:
        return date(y, mth, d)
    except ValueError:
        return None


def _labeled_amount(text: str) -> int | None:
    patterns = [
        rf"(?:valor\s+(?:do\s+documento|a\s+pagar|cobrado|total|da\s+fatura|pago)|total\s+a\s+pagar|"
        rf"valor\s+total|total\s+da\s+fatura|valor)\s*:?\s*{_MONEY}",
        rf"total\s*:?\s*{_MONEY}",
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            return round(parse_number(m.group(1)) * 100)
    amounts = [round(parse_number(a) * 100) for a in re.findall(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})", text)]
    return max(amounts) if amounts else None


def parse_text(text: str, today: date) -> Extraction:
    ex = Extraction()
    if not text.strip():
        ex.warnings.append("Nenhum texto legível encontrado no documento.")
        return ex
    norm = normalize(text)

    for m in LINE_RX.finditer(text):
        decoded = decode_boleto(m.group(0), today)
        if decoded:
            ex.barcode = decoded["barcode"]
            ex.barcode_valid = decoded["valid"]
            if decoded["valid"] is False:
                ex.warnings.append("A linha digitável não passou na verificação: confira os dígitos.")
            else:
                ex.amount_cents = decoded["amount_cents"]
                ex.due_date = decoded["due_date"]
            ex.institution = decoded["institution"]
            ex.kind = "bill"
            break

    m = re.search(rf"vencimento\s*:?\s*{_DATE}", text, re.I)
    if m and not ex.due_date:
        ex.due_date = _to_date(m)
    if ex.amount_cents is None:
        ex.amount_cents = _labeled_amount(text)
    dates = [d for d in (_to_date(x) for x in re.finditer(_DATE, text)) if d]
    if dates:
        ex.issue_date = min(dates, key=lambda d: abs((d - today).days)) if not ex.due_date else None
        if ex.issue_date and ex.issue_date > today:
            ex.issue_date = None

    m = re.search(r"(?:benefici[aá]rio|cedente|favorecido|recebedor|para)\s*:?\s*([^\n]{3,80})", text, re.I)
    if m:
        ex.beneficiary = (
            re.split(r"\s{2,}|CNPJ|CPF", m.group(1).strip(), maxsplit=1)[0].strip(" :-")[:80] or None
        )
    m = re.search(
        r"(?:n[º°o]\.?\s*(?:do\s+)?documento|nosso\s+n[úu]mero|n[úu]mero\s+da\s+fatura)\s*:?\s*([\w./-]{3,30})",
        text,
        re.I,
    )
    if m:
        ex.document_number = m.group(1)
    m = re.search(r"chave\s+pix\s*:?\s*([\w.@+-]{6,80})", text, re.I)
    if m:
        ex.pix_key = m.group(1)
    if not ex.institution:
        ex.institution = next(
            (i for i in INSTITUTIONS if re.search(rf"\b{re.escape(i)}\b", text, re.I)), None
        )

    if re.search(r"\bpix\b", norm) and re.search(r"comprovante|transferencia", norm):
        ex.kind = "pix"
        if re.search(r"\b(recebid[oa]|voce recebeu|credito)\b", norm):
            ex.direction = "income"
    elif re.search(r"nota fiscal|nf-?e|cupom fiscal|danfe", norm):
        ex.kind = "invoice"
    elif re.search(r"\bfatura\b", norm) and ex.kind == "other":
        ex.kind = "bill"
    elif re.search(r"\b(recibo|comprovante)\b", norm) and ex.kind == "other":
        ex.kind = "receipt"

    ex.category_name = keyword_category(norm)
    ex.recurring_hint = bool(
        re.search(
            r"\b(energia|luz|agua|internet|telefone|celular|condominio|aluguel|mensalidade|plano)\b", norm
        )
    )
    ex.title = ex.category_name or ex.beneficiary or ex.institution
    if ex.amount_cents is None:
        ex.warnings.append("Valor não identificado.")
    return ex
