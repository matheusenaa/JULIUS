"""Extração determinística de informações financeiras de frases em português.

É a base do Quick Input quando não há IA configurada (ou ela falha) e também
a rede de segurança quando a IA devolve algo inválido.
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.services.categorizer import normalize
from app.services.dates import MONTHS_PT, add_months

# ---------- Valores ----------
_NUM = r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?"
_MONEY = re.compile(
    rf"(?P<rs>r\$\s*)?(?P<num>{_NUM})(?P<mil>\s*mil\b)?(?P<after>\s*(?:reais|real|conto|contos|pila|r\$))?",
    re.I,
)
_INSTALLMENTS = re.compile(r"\b(?:em\s+)?(\d{1,3})\s*(?:x\b|vezes\b|parcelas\b)", re.I)
_DAY = re.compile(r"\bdia\s+(\d{1,2})\b", re.I)
_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")


def parse_number(raw: str) -> float:
    raw = raw.strip()
    if "," in raw:  # padrão brasileiro: 1.234,56
        return float(raw.replace(".", "").replace(",", "."))
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", raw):  # 1.200 = mil e duzentos
        return float(raw.replace(".", ""))
    return float(raw)


def extract_amount(text: str) -> int | None:
    """Valor em centavos. Ignora números que são dia, data ou quantidade de parcelas."""
    blocked: list[tuple[int, int]] = []
    for rx in (_INSTALLMENTS, _DAY, _DATE):
        blocked += [m.span() for m in rx.finditer(text)]

    candidates = []
    for m in _MONEY.finditer(text):
        start, end = m.span("num")
        if any(s <= start < e for s, e in blocked):
            continue
        value = parse_number(m.group("num"))
        if m.group("mil"):
            value *= 1000
        explicit = bool(m.group("rs") or m.group("after"))
        candidates.append((explicit, value))
    if not candidates:
        return None
    explicit = [v for e, v in candidates if e]
    value = explicit[0] if explicit else candidates[0][1]
    cents = round(value * 100)
    return cents if cents > 0 else None


def extract_installments(text: str) -> int:
    m = _INSTALLMENTS.search(text)
    if m:
        n = int(m.group(1))
        if 2 <= n <= 120:
            return n
    return 1


# ---------- Datas ----------
FUTURE_WORDS = re.compile(
    r"\b(vou|vai|vamos|irei|ira|previsto|prevista|agendad[oa]|amanha|vence|vencimento)\b"
)


def extract_date(norm: str, original: str, today: date) -> tuple[date, bool]:
    """Retorna (data, é_futuro_explícito)."""
    future = bool(FUTURE_WORDS.search(norm))
    if "anteontem" in norm:
        return today - timedelta(days=2), False
    if "ontem" in norm:
        return today - timedelta(days=1), False
    if "amanha" in norm:
        return today + timedelta(days=1), True

    m = _DATE.search(original)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        y = int(m.group(3)) if m.group(3) else today.year
        if y < 100:
            y += 2000
        try:
            return date(y, mo, d), date(y, mo, d) > today
        except ValueError:
            pass

    m = _DAY.search(original)
    if m:
        day = int(m.group(1))
        if 1 <= day <= 31:
            candidate = add_months(today.replace(day=1), 0, day)
            if future and candidate < today:
                candidate = add_months(today.replace(day=1), 1, day)
            elif not future and candidate > today:
                candidate = add_months(today.replace(day=1), -1, day)
            return candidate, candidate > today
    return today, False


# ---------- Tipo, forma de pagamento, recorrência ----------
INCOME_RX = re.compile(
    r"\b(recebi|receber|recebo|recebemos|ganhei|ganho|salario|entrou|caiu|depositaram|"
    r"reembolso|reembolsaram|rendimento|rendeu|vendi|freela|pagaram|me pagou|me pagaram)\b"
)
TRANSFER_RX = re.compile(r"\b(transferi|transferencia|transferir|guardei|apliquei|resgatei|movi)\b")
INVOICE_RX = re.compile(r"\bpaguei (a )?fatura\b|\bpagamento da fatura\b")

PAYMENT_RX = [
    ("pix", re.compile(r"\bpix\b")),
    ("credit", re.compile(r"\b(credito|cartao de credito|no cartao|parcelad[oa]|\d+\s*x)\b")),
    ("debit", re.compile(r"\bdebito\b")),
    ("cash", re.compile(r"\b(dinheiro|especie|em maos)\b")),
    ("boleto", re.compile(r"\bboleto\b")),
]

RECURRENCE_RX = re.compile(
    r"\b(por mes|todo mes|todos os meses|mensal|mensalmente|mensalidade|ao mes|"
    r"toda semana|semanal|por ano|anual|todo ano)\b"
)


def extract_type(norm: str) -> str:
    if INVOICE_RX.search(norm) or TRANSFER_RX.search(norm):
        return "transfer"
    if INCOME_RX.search(norm):
        return "income"
    return "expense"


def extract_payment(norm: str) -> str | None:
    for method, rx in PAYMENT_RX:
        if rx.search(norm):
            return method
    return None


def extract_recurrence(norm: str) -> str | None:
    m = RECURRENCE_RX.search(norm)
    if not m:
        return None
    word = m.group(1)
    if "semana" in word or "semanal" in word:
        return "weekly"
    if "ano" in word or "anual" in word:
        return "yearly"
    return "monthly"


# ---------- Categorias por palavra-chave ----------
# (regex sobre o texto normalizado, nome da categoria/subcategoria padrão)
CATEGORY_KEYWORDS: list[tuple[str, str]] = [
    (
        r"\b(posto|gasolina|etanol|alcool|diesel|abasteci|abastecer|abastecimento|combustivel|gnv)\b",
        "Combustível",
    ),
    (r"\b(uber|99 ?pop|99 ?taxi|99app|taxi|cabify|indriver)\b", "Uber/Táxi"),
    (r"\b(onibus|metro|trem|brt|passagem de onibus|bilhete unico)\b", "Transporte público"),
    (r"\b(estacionamento|estacionei|zona azul)\b", "Estacionamento"),
    (r"\b(pedagio|sem parar|conectcar)\b", "Pedágio"),
    (
        r"\b(mecanico|oficina|revisao do carro|pneu|troca de oleo|lava jato|lavagem)\b",
        "Manutenção do veículo",
    ),
    (r"\b(mercado|supermercado|feira|hortifruti|atacadao|assai|carrefour|compras do mes)\b", "Mercado"),
    (r"\b(ifood|delivery|rappi|pedi comida|aiqfome)\b", "Delivery"),
    (
        r"\b(almoco|almocei|jantar|jantei|restaurante|churrascaria|rodizio|pizzaria|pizza|hamburguer)\b",
        "Restaurantes",
    ),
    (r"\b(lanche|lanchonete|padaria|cafe|cafeteria|salgado|sorvete|acai)\b", "Lanches"),
    (r"\b(aluguel)\b", "Aluguel"),
    (r"\b(condominio)\b", "Condomínio"),
    (r"\b(luz|energia|enel|cemig|copel|light|celpe|coelba)\b", "Energia"),
    (r"\b(agua|sabesp|saneamento|copasa)\b", "Água"),
    (r"\b(internet|wifi|fibra|banda larga)\b", "Internet"),
    (r"\b(plano de celular|conta de celular|recarga|telefone|conta da (vivo|claro|tim|oi))\b", "Celular"),
    (r"\b(gas de cozinha|botijao|conta de gas|comgas)\b", "Gás"),
    (r"\b(farmacia|remedio|remedios|drogaria|medicamento)\b", "Farmácia"),
    (r"\b(consulta|medico|medica|dentista|psicologo|psicologa|terapia|fisioterapia)\b", "Consultas"),
    (r"\b(plano de saude|unimed|amil|hapvida|bradesco saude)\b", "Plano de saúde"),
    (r"\b(exame|exames|laboratorio)\b", "Exames"),
    (r"\b(faculdade|escola|mensalidade escolar|colegio)\b", "Mensalidade"),
    (r"\b(curso|udemy|alura|aula)\b", "Cursos"),
    (r"\b(livro|livros|livraria)\b", "Livros"),
    (r"\b(cinema|filme)\b", "Cinema"),
    (r"\b(bar|cerveja|chopp|balada|boteco)\b", "Bares"),
    (r"\b(show|ingresso|teatro|festival|evento)\b", "Shows e eventos"),
    (r"\b(jogo|game|steam|playstation|xbox)\b", "Jogos"),
    (r"\b(camisa|camiseta|calca|blusa|vestido|roupa|roupas|bermuda|saia|jaqueta|casaco)\b", "Roupas"),
    (r"\b(tenis|sapato|sandalia|chinelo|bota)\b", "Calçados"),
    (r"\b(bolsa|relogio|oculos|bijuteria|acessorio)\b", "Acessórios"),
    (
        r"\b(netflix|spotify|disney|hbo|max|prime video|youtube premium|globoplay|deezer|streaming)\b",
        "Streaming",
    ),
    (r"\b(academia|smartfit|crossfit|pilates)\b", "Academia"),
    (r"\b(icloud|google one|chatgpt|assinatura de app|aplicativo)\b", "Aplicativos"),
    (r"\b(iptu)\b", "IPTU"),
    (r"\b(ipva|licenciamento)\b", "IPVA"),
    (r"\b(imposto de renda|darf)\b", "Imposto de renda"),
    (r"\b(hotel|pousada|airbnb|hospedagem)\b", "Hospedagem"),
    (r"\b(passagem aerea|passagens|voo|aviao)\b", "Passagens"),
    (r"\b(viagem|viajei)\b", "Viagens"),
    (r"\b(presente|presentes)\b", "Presentes"),
    (r"\b(celular novo|notebook|computador|fone|eletronico|tv|televisao)\b", "Eletrônicos"),
    (r"\b(movel|moveis|sofa|cama|geladeira|fogao|maquina de lavar)\b", "Móveis"),
    (r"\b(investi|investimento|tesouro|cdb|acoes|fii)\b", "Investimentos"),
    (r"\b(lazer|passeio|diversao)\b", "Lazer"),
    (r"\b(salario|pagamento do mes|holerite)\b", "Salário"),
    (r"\b(freela|freelance|bico|servico extra)\b", "Freelance"),
    (r"\b(vendi|venda)\b", "Vendas"),
    (r"\b(rendimento|rendeu|juros|dividendos)\b", "Rendimentos"),
    (r"\b(reembolso|reembolsaram|estorno)\b", "Reembolso"),
]
_CATEGORY_RX = [(re.compile(p), name) for p, name in CATEGORY_KEYWORDS]


def keyword_category(norm: str) -> str | None:
    for rx, name in _CATEGORY_RX:
        if rx.search(norm):
            return name
    return None


# ---------- Descrição ----------
FILLER = {
    "gastei",
    "paguei",
    "comprei",
    "recebi",
    "receber",
    "vou",
    "vai",
    "abasteci",
    "ganhei",
    "transferi",
    "reais",
    "real",
    "r",
    "de",
    "do",
    "da",
    "dos",
    "das",
    "no",
    "na",
    "nos",
    "nas",
    "em",
    "com",
    "por",
    "para",
    "pra",
    "pro",
    "o",
    "a",
    "os",
    "as",
    "um",
    "uma",
    "meu",
    "minha",
    "hoje",
    "ontem",
    "anteontem",
    "amanha",
    "dia",
    "e",
    "foi",
    "x",
    "vezes",
    "parcelas",
    "conto",
    "contos",
    "mes",
    "todo",
    "cada",
    "ao",
    "pix",
    "debito",
    "credito",
    "cartao",
    "dinheiro",
    "mil",
    "conta",
    "minhas",
    "meus",
    "custa",
    "custou",
    "sao",
    "esta",
    "ta",
    "valor",
}


def make_description(original: str) -> str:
    text = _DATE.sub(" ", original)
    text = _INSTALLMENTS.sub(" ", text)
    text = re.sub(r"r\$\s*", " ", text, flags=re.I)
    text = re.sub(rf"\b({_NUM})\b", " ", text)
    words = [w for w in re.split(r"\s+", text) if w]
    kept = [w for w in words if normalize(w) not in FILLER and normalize(w)]
    desc = " ".join(kept).strip(" ,.;:-")
    if not desc:
        return ""
    return desc[0].upper() + desc[1:]


@dataclass
class LocalParse:
    type: str
    amount_cents: int | None
    occurred_on: date
    future: bool
    description: str
    installments: int
    payment_method: str | None
    recurrence: str | None
    day_of_month: int | None
    category_name: str | None
    notes: list[str] = field(default_factory=list)


def parse(text: str, today: date) -> LocalParse:
    norm = normalize(text)
    occurred_on, future = extract_date(norm, text, today)
    recurrence = extract_recurrence(norm)
    day = _DAY.search(text)
    return LocalParse(
        type=extract_type(norm),
        amount_cents=extract_amount(text),
        occurred_on=occurred_on,
        future=future,
        description=make_description(text),
        installments=extract_installments(text),
        payment_method=extract_payment(norm),
        recurrence=recurrence,
        day_of_month=int(day.group(1)) if day and recurrence else None,
        category_name=keyword_category(norm),
    )


def month_from_text(norm: str, today: date) -> date | None:
    """'setembro' → 1º de setembro mais recente (não futuro)."""
    for i, name in enumerate(MONTHS_PT):
        if re.search(rf"\b{normalize(name)}\b", norm):
            year = today.year if i + 1 <= today.month else today.year - 1
            m = re.search(rf"\b{normalize(name)}\s+(?:de\s+)?(\d{{4}})\b", norm)
            if m:
                year = int(m.group(1))
            return date(year, i + 1, 1)
    return None
