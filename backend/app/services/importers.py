"""Importação de extratos: OFX (padrão dos bancos) e CSV.

Fluxo em duas etapas: PRÉVIA (nada é gravado; duplicados e categorias sugeridas são
marcados) → CONFIRMAÇÃO das linhas escolhidas. Cada linha tem uma referência estável
(`import_ref`); importar o mesmo extrato de novo não duplica lançamentos.

Para um novo formato (ex.: Excel de um banco específico), basta uma função
`parse_<formato>(bytes) -> list[Row]` registrada em PARSERS.
"""

import csv
import hashlib
import io
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.nlp_pt import keyword_category, parse_number
from app.ai.quick_input import _find_category
from app.errors import BadRequest
from app.models import Category, Transaction
from app.services import categorizer
from app.services.categorizer import normalize


@dataclass
class Row:
    occurred_on: date
    amount_cents: int  # com sinal: negativo = saída
    description: str
    external_id: str | None = None


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise BadRequest("Não foi possível ler o arquivo (codificação desconhecida).")


def _ofx_tag(block: str, name: str) -> str | None:
    m = re.search(rf"<{name}>([^<\r\n]+)", block, re.I)
    return m.group(1).strip() if m else None


def parse_ofx(data: bytes) -> list[Row]:
    text = _decode(data)
    rows = []
    for block in re.findall(
        r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|(?=</BANKTRANLIST>))", text, re.S | re.I
    ):

        def tag(name: str, block: str = block) -> str | None:
            return _ofx_tag(block, name)

        raw_date, raw_amount = tag("DTPOSTED"), tag("TRNAMT")
        if not raw_date or not raw_amount:
            continue
        try:
            when = datetime.strptime(raw_date[:8], "%Y%m%d").date()
            amount = round(float(raw_amount.replace(",", ".")) * 100)
        except ValueError:
            continue
        desc = tag("MEMO") or tag("NAME") or "Lançamento importado"
        rows.append(Row(when, amount, desc[:200], tag("FITID")))
    if not rows:
        raise BadRequest("Nenhuma transação encontrada no arquivo OFX.")
    return rows


_DATE_FORMATS = ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%Y")


def _parse_date(value: str) -> date | None:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value.strip()[:10], fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(value: str) -> int | None:
    v = value.strip().replace("R$", "").replace(" ", "")
    neg = v.startswith("-") or (v.startswith("(") and v.endswith(")"))
    v = v.strip("-()+")
    if not v:
        return None
    try:
        cents = (
            round(parse_number(v) * 100)
            if ("," in v or re.fullmatch(r"\d{1,3}(\.\d{3})+", v))
            else round(float(v) * 100)
        )
    except ValueError:
        return None
    return -cents if neg else cents


def parse_csv(data: bytes) -> list[Row]:
    text = _decode(data)
    sample = text[:4096]
    delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    reader = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    if len(reader) < 2:
        raise BadRequest("O CSV está vazio.")
    header = [normalize(h) for h in reader[0]]

    def col(*names: str) -> int | None:
        for i, h in enumerate(header):
            if any(n in h for n in names):
                return i
        return None

    i_date = col("data", "date")
    i_desc = col("descricao", "historico", "lancamento", "description", "memo")
    i_amount = col("valor", "amount", "quantia")
    i_type = col("tipo")
    if i_date is None or i_amount is None:
        raise BadRequest(
            "Não encontrei as colunas de data e valor no CSV (cabeçalhos esperados: Data, Descrição, Valor)."
        )
    rows = []
    for line in reader[1:]:
        if len(line) <= max(i_date, i_amount):
            continue
        when, cents = _parse_date(line[i_date]), _parse_amount(line[i_amount])
        if not when or not cents:
            continue
        if (
            i_type is not None
            and len(line) > i_type
            and normalize(line[i_type]).startswith("despesa")
            and cents > 0
        ):
            cents = -cents  # exportação do próprio JULIUS: valor positivo + coluna Tipo
        desc = (line[i_desc] if i_desc is not None and len(line) > i_desc else "") or "Lançamento importado"
        rows.append(Row(when, cents, desc.strip()[:200]))
    if not rows:
        raise BadRequest("Nenhuma linha válida no CSV.")
    return rows


PARSERS = {"ofx": parse_ofx, "csv": parse_csv}


def detect(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".ofx") or b"<OFX>" in data[:4000].upper() or b"OFXHEADER" in data[:200].upper():
        return "ofx"
    if name.endswith((".csv", ".txt")):
        return "csv"
    raise BadRequest("Formato não suportado. Envie um extrato OFX ou CSV.")


def _ref(account_id: str, row: Row, seq: int) -> str:
    base = (
        f"{account_id}|{row.external_id}"
        if row.external_id
        else (f"{account_id}|{row.occurred_on}|{row.amount_cents}|{normalize(row.description)}|{seq}")
    )
    return hashlib.sha256(base.encode()).hexdigest()[:64]


def preview(db: Session, user_id: str, account_id: str, rows: list[Row]) -> list[dict]:
    cats = db.scalars(
        select(Category).where(Category.user_id == user_id, Category.deleted_at.is_(None))
    ).all()
    by_id = {c.id: c for c in cats}
    seen: dict[tuple, int] = {}
    refs = []
    for r in rows:
        key = (r.occurred_on, r.amount_cents, normalize(r.description))
        seen[key] = seen.get(key, 0) + 1
        refs.append(_ref(account_id, r, seen[key]))
    existing = set(
        db.scalars(
            select(Transaction.import_ref).where(
                Transaction.user_id == user_id, Transaction.import_ref.in_(refs)
            )
        )
    )
    items = []
    for r, ref in zip(rows, refs, strict=True):
        tx_type = "income" if r.amount_cents > 0 else "expense"
        learned = by_id.get(categorizer.suggest_from_rules(db, user_id, r.description) or "")
        cat = (
            learned
            if learned and learned.kind == tx_type
            else _find_category(cats, keyword_category(normalize(r.description)), tx_type)
        )
        items.append(
            {
                **asdict(r),
                "type": tx_type,
                "amount_cents": abs(r.amount_cents),
                "import_ref": ref,
                "category_id": cat.id if cat else None,
                "duplicate": ref in existing,
            }
        )
    return items
