"""Assistente financeiro.

1. A pergunta vira uma INTENÇÃO estruturada (regras locais; IA só se as regras não entenderem).
2. O backend consulta o banco e calcula.
3. A resposta é montada com os números calculados. A IA, quando usada para
   conselhos, recebe apenas esses fatos e é instruída a não inventar outros.
"""

import json
import logging
import re
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.nlp_pt import keyword_category, month_from_text
from app.ai.providers import AIUnavailable, get_provider
from app.models import Category, Recurrence, Transaction, User
from app.services import analytics, ledger
from app.services.categorizer import normalize
from app.services.dates import MONTHS_PT, add_months, local_today, month_end, month_start, period_bounds
from app.services.transactions import brl

log = logging.getLogger("julius.assistant")

NUMBERS = {
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
    "dez": 10,
    "onze": 11,
    "doze": 12,
}

INTENTS = [
    ("forecast", r"daqui a|se eu continuar|projec|vou ter|terei|futuro"),
    ("can_spend", r"posso gastar|ainda posso|quanto sobra|vai sobrar"),
    (
        "top_category",
        r"maior (categoria|gasto|despesa)|onde (eu )?(mais )?gast|com o que (eu )?(mais )?gast|o que mais gast",
    ),
    ("fixed", r"(despesas|gastos|contas) fix"),
    ("upcoming", r"vencimento|vence|a pagar|proximas contas|contas a vencer"),
    ("average", r"\bmedia\b"),
    ("savings", r"economizei|guardei|poupei|sobrou"),
    ("compare", r"compar|aumentou|aumentaram|diminuiu|em relacao"),
    ("advice", r"dica|como (posso )?(economizar|gastar menos|organizar)|conselho|sugest|me ajud"),
    ("balance", r"quanto (eu )?tenho|saldo|disponivel|dinheiro (eu )?tenho"),
    ("income", r"recebi|ganhei|receitas?|entrou|renda"),
    ("spent", r"gastei|gasto|gastos|despesas?|paguei"),
]

HELP = (
    "Ainda não entendi essa pergunta. Exemplos do que sei responder:\n"
    "• Quanto gastei com combustível este mês?\n• Quanto ainda posso gastar este mês?\n"
    "• Qual foi minha maior categoria de gastos?\n• Quais despesas fixas tenho?\n"
    "• Quanto economizei nos últimos três meses?\n• Quanto terei daqui a seis meses?"
)

ADVICE_SYSTEM = """Você é o JULIUS, assistente financeiro pessoal. Responda em português, de forma simples e curta
(até 6 frases), sem jargões. Use SOMENTE os números fornecidos em FATOS; nunca invente valores nem faça
contas novas. Se os fatos forem insuficientes, diga isso. Sugestões são sugestões, não certezas; projeções
são estimativas. Devolva JSON: {"answer": "..."}"""

CLASSIFY_SYSTEM = """Classifique a pergunta financeira do usuário. Devolva JSON:
{"intent": one of [spent, income, balance, can_spend, top_category, fixed, upcoming, average, savings,
compare, forecast, advice, unknown], "category_id": id da lista ou null, "start": "AAAA-MM-DD" ou null,
"end": "AAAA-MM-DD" ou null, "months": inteiro ou null}"""


def _months_in(norm: str, default: int) -> int:
    m = re.search(r"(\d{1,2}|" + "|".join(NUMBERS) + r")\s+(mes|meses)", norm)
    if not m:
        return default
    raw = m.group(1)
    return max(1, min(int(raw) if raw.isdigit() else NUMBERS[raw], 24))


def _period(norm: str, today: date) -> tuple[date, date, str]:
    if "hoje" in norm:
        return today, today, "hoje"
    if "ontem" in norm:
        d = today - timedelta(days=1)
        return d, d, "ontem"
    if re.search(r"(esta|essa|nesta|nessa) semana", norm):
        s, _ = period_bounds("week", today)
        return s, today, "nesta semana"
    if re.search(r"semana passada", norm):
        s, e = period_bounds("week", today - timedelta(days=7))
        return s, e, "na semana passada"
    m = re.search(r"ultimos (\d{1,3}) dias", norm)
    if m:
        return today - timedelta(days=int(m.group(1)) - 1), today, f"nos últimos {m.group(1)} dias"
    if re.search(r"mes passado|ultimo mes", norm):
        s = add_months(month_start(today), -1)
        return s, month_end(s), f"em {MONTHS_PT[s.month - 1]}"
    named = month_from_text(norm, today)
    if named:
        return named, min(month_end(named), today), f"em {MONTHS_PT[named.month - 1]} de {named.year}"
    if re.search(r"(este|esse|neste|nesse|no) ano", norm):
        return date(today.year, 1, 1), today, f"em {today.year}"
    return month_start(today), today, "este mês"


def _category(db: Session, user_id: str, norm: str) -> Category | None:
    cats = db.scalars(
        select(Category).where(Category.user_id == user_id, Category.deleted_at.is_(None))
    ).all()
    best = None
    for c in cats:
        n = normalize(c.name)
        if len(n) >= 3 and re.search(rf"\b{re.escape(n)}\b", norm):
            if best is None or len(n) > len(normalize(best.name)):
                best = c
    if best:
        return best
    name = keyword_category(norm)
    if name:
        return next((c for c in cats if c.name == name), None)
    return None


def _spent_in(db, user_id, start, end, category: Category | None, tx_type="expense") -> tuple[int, int]:
    cond = [
        Transaction.user_id == user_id,
        Transaction.deleted_at.is_(None),
        Transaction.status == "paid",
        Transaction.type == tx_type,
        Transaction.occurred_on.between(start, end),
    ]
    if category is not None:
        children = select(Category.id).where(Category.parent_id == category.id)
        cond.append(Transaction.category_id.in_(children) | (Transaction.category_id == category.id))
    total, count = db.execute(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0), func.count()).where(*cond)
    ).one()
    return int(total), int(count)


def _facts(db: Session, user_id: str, today: date) -> dict:
    """Resumo numérico calculado pelo backend, entregue à IA para conselhos."""
    s, e = month_start(today), today
    totals = ledger.totals_by_type(db, user_id, s, e)
    return {
        "hoje": today.isoformat(),
        "saldo_atual": brl(analytics.current_balance(db, user_id, today)),
        "mes_atual": {"receitas": brl(totals["income"]), "despesas": brl(totals["expense"])},
        "saldo_projetado_fim_do_mes": brl(
            analytics.projected_balance(db, user_id, today, month_end(today))["projected_cents"]
        ),
        "media_mensal_ultimos_meses": {
            k: (brl(v) if isinstance(v, int) and k != "months_with_data" else v)
            for k, v in analytics.averages(db, user_id, today).items()
        },
        "maiores_categorias_mes": [
            {"categoria": c["name"], "total": brl(c["total_cents"])}
            for c in analytics.expenses_by_category(db, user_id, s, e)[:5]
        ],
        "orcamentos": [
            {"categoria": b["name"], "limite": brl(b["amount_cents"]), "gasto": brl(b["spent_cents"])}
            for b in analytics.budgets_status(db, user_id, today)
        ],
        "alertas": [i["text"] for i in analytics.insights(db, user_id, today)],
    }


def _classify_with_ai(question: str, db: Session, user_id: str, today: date) -> dict | None:
    provider = get_provider()
    if provider is None:
        return None
    cats = db.scalars(
        select(Category).where(Category.user_id == user_id, Category.deleted_at.is_(None))
    ).all()
    prompt = f"Hoje: {today.isoformat()}\nCategorias:\n" + "\n".join(f"{c.id} | {c.name}" for c in cats)
    prompt += f"\n\nPergunta: {question}"
    try:
        return provider.generate_json(CLASSIFY_SYSTEM, prompt)
    except AIUnavailable:
        return None


def answer(db: Session, user: User, question: str, today: date | None = None) -> dict:
    today = today or local_today()
    norm = normalize(question)
    intent = next((name for name, rx in INTENTS if re.search(rx, norm)), "unknown")
    start, end, label = _period(norm, today)
    category = _category(db, user.id, norm)
    months = None
    engine = "rules"

    if intent == "unknown":
        ai = _classify_with_ai(question, db, user.id, today)
        if ai and ai.get("intent") in {n for n, _ in INTENTS}:
            engine = "ai"
            intent = ai["intent"]
            cat = db.get(Category, ai.get("category_id") or "")
            if cat and cat.user_id == user.id:
                category = cat
            try:
                if ai.get("start") and ai.get("end"):
                    start, end = date.fromisoformat(ai["start"]), date.fromisoformat(ai["end"])
                    label = f"de {start.strftime('%d/%m/%Y')} a {end.strftime('%d/%m/%Y')}"
            except ValueError:
                pass
            if isinstance(ai.get("months"), int):
                months = max(1, min(ai["months"], 24))

    uid = user.id
    data: dict = {}
    estimate = False

    if intent in ("spent", "income"):
        tx_type = "expense" if intent == "spent" else "income"
        total, count = _spent_in(db, uid, start, end, category if tx_type == "expense" else None, tx_type)
        what = f" com {category.name}" if category and tx_type == "expense" else ""
        verb = "gastou" if tx_type == "expense" else "recebeu"
        if count == 0:
            text = f"Não encontrei {'gastos' if tx_type == 'expense' else 'receitas'}{what} {label}."
        else:
            text = f"Você {verb} {brl(total)}{what} {label} ({count} lançamento{'s' if count > 1 else ''})."
        data = {
            "total_cents": total,
            "count": count,
            "start": start,
            "end": end,
            "category": category.name if category else None,
        }

    elif intent == "balance":
        accounts = ledger.account_balances(db, uid, as_of=today)
        total = analytics.current_balance(db, uid, today)
        text = f"Seu saldo disponível hoje é {brl(total)}, somando as contas (sem cartões de crédito)."
        data = {"balance_cents": total, "accounts": accounts}

    elif intent == "can_spend":
        proj = analytics.projected_balance(db, uid, today, month_end(today))
        estimate = True
        p = proj["projected_cents"]
        if p > 0:
            text = (
                f"Considerando seu saldo de {brl(proj['current_cents'])}, as contas previstas e recorrentes "
                f"e as faturas que vencem até o fim do mês, você ainda pode gastar cerca de {brl(p)} "
                f"este mês sem ficar negativo. É uma estimativa: depende de os lançamentos previstos se confirmarem."
            )
        else:
            text = (
                f"Pela estimativa, você termina o mês com {brl(p)}. Ou seja, os compromissos previstos já "
                f"superam o saldo atual — melhor evitar novos gastos não essenciais."
            )
        budgets = [
            b for b in analytics.budgets_status(db, uid, today) if b["spent_cents"] < b["amount_cents"]
        ]
        if budgets:
            text += (
                " Nos orçamentos: "
                + "; ".join(
                    f"{b['name']}: restam {brl(b['amount_cents'] - b['spent_cents'])}" for b in budgets[:4]
                )
                + "."
            )
        data = proj

    elif intent == "top_category":
        cats = analytics.expenses_by_category(db, uid, start, end)
        if not cats:
            text = f"Não há despesas registradas {label}."
        else:
            top = cats[0]
            text = f"Sua maior categoria de gastos {label} foi {top['name']}: {brl(top['total_cents'])} ({round(top['share'] * 100)}% do total)."
            if len(cats) > 1:
                text += (
                    " Em seguida: "
                    + ", ".join(f"{c['name']} ({brl(c['total_cents'])})" for c in cats[1:3])
                    + "."
                )
        data = {"categories": cats[:5]}

    elif intent == "fixed":
        recs = db.scalars(
            select(Recurrence).where(
                Recurrence.user_id == uid,
                Recurrence.deleted_at.is_(None),
                Recurrence.type == "expense",
                (Recurrence.end_date.is_(None)) | (Recurrence.end_date >= today),
            )
        ).all()
        monthly = [r for r in recs if r.frequency == "monthly"]
        if not recs:
            text = "Você ainda não cadastrou despesas fixas (recorrentes). Cadastre aluguel, internet etc. para eu acompanhar."
        else:
            total = sum(r.amount_cents for r in monthly)
            lines = "\n".join(
                f"• {r.description}: {brl(r.amount_cents)}"
                + (f" (todo dia {r.day_of_month})" if r.day_of_month else "")
                for r in recs
            )
            text = f"Suas despesas fixas cadastradas:\n{lines}\nTotal mensal: {brl(total)}."
            data = {"total_monthly_cents": total}

    elif intent == "upcoming":
        items = analytics.upcoming(db, uid, today, 30)
        if not items:
            text = "Não há contas previstas para os próximos 30 dias."
        else:
            text = "Próximos vencimentos:\n" + "\n".join(
                f"• {i['date'].strftime('%d/%m')} — {i['description']}: {brl(i['amount_cents'])}"
                + (" (atrasado)" if i["overdue"] else "")
                for i in items[:10]
            )
        data = {"items": items[:10]}

    elif intent == "average":
        n = months or _months_in(norm, 3)
        avg = analytics.averages(db, uid, today, n)
        if not avg["months_with_data"]:
            text = "Ainda não há nenhum mês completo com lançamentos para calcular a média."
        else:
            text = (
                f"Nos últimos {avg['months_with_data']} mês(es) completos, você gastou em média "
                f"{brl(avg['expense_cents'])} por mês e recebeu {brl(avg['income_cents'])}."
            )
            if avg["months_with_data"] < n:
                text += f" (Só há dados de {avg['months_with_data']} dos {n} meses pedidos.)"
        data = avg

    elif intent == "savings":
        n = months or _months_in(norm, 3)
        series = analytics.monthly_series(db, uid, add_months(month_start(today), -1), n)
        with_data = [m for m in series if m["income"] or m["expense"]]
        if not with_data:
            text = "Não há lançamentos suficientes nos meses anteriores para calcular quanto você economizou."
        else:
            net = sum(m["net_cents"] for m in series)
            word = "economizou" if net >= 0 else "gastou a mais do que recebeu"
            text = f"Nos últimos {n} meses completos você {word}: {brl(abs(net))}.\n" + "\n".join(
                f"• {MONTHS_PT[m['month'].month - 1]}: {brl(m['net_cents'])}" for m in series
            )
            if len(with_data) < n:
                text += f"\n(Só há lançamentos em {len(with_data)} desses meses.)"
        data = {"series": series}

    elif intent == "forecast":
        n = months or _months_in(norm, 6)
        f = analytics.forecast(db, uid, today, n)
        estimate = True
        if not f["available"]:
            text = f"Ainda não consigo projetar: {f['reason']} Seu saldo atual é {brl(f['current_cents'])}."
        else:
            final = f["points"][-1]["balance_cents"]
            text = (
                f"Estimativa: mantendo o ritmo médio dos últimos {f['based_on_months']} mês(es) "
                f"({'+' if f['avg_net_cents'] >= 0 else ''}{brl(f['avg_net_cents'])} por mês), você teria cerca de "
                f"{brl(final)} daqui a {n} meses. É uma projeção simples, não uma garantia."
            )
        data = f

    elif intent == "compare":
        r = analytics.report(db, uid, "month", today)
        prev = r["previous"]
        diff = r["expense_cents"] - prev["expense_cents"]
        text = (
            f"Este mês (até hoje) você gastou {brl(r['expense_cents'])}; no mês passado inteiro, "
            f"{brl(prev['expense_cents'])}."
        )
        if prev["expense_cents"]:
            text += f" Diferença: {'+' if diff >= 0 else '-'}{brl(abs(diff))}."
        grew = [c for c in r["by_category"] if c["total_cents"] > c["previous_cents"] > 0][:3]
        if grew:
            text += " Categorias que já superaram o mês passado: " + ", ".join(c["name"] for c in grew) + "."
        data = {"current_cents": r["expense_cents"], "previous_cents": prev["expense_cents"]}

    elif intent == "advice":
        facts = _facts(db, uid, today)
        provider = get_provider()
        text = None
        if provider is not None:
            try:
                out = provider.generate_json(
                    ADVICE_SYSTEM,
                    f"FATOS:\n{json.dumps(facts, ensure_ascii=False, default=str)}\n\nPergunta: {question}",
                )
                if isinstance(out.get("answer"), str):
                    text, engine = out["answer"].strip(), "ai"
            except AIUnavailable:
                pass
        if not text:
            tips = facts["alertas"] or ["Nenhum alerta no momento."]
            text = (
                "Alguns pontos a partir dos seus dados:\n"
                + "\n".join(f"• {t}" for t in tips)
                + "\nDica geral: defina orçamentos para as categorias que mais pesam e cadastre suas contas fixas."
            )
        data = facts

    else:
        text = HELP

    return {"answer": text, "intent": intent, "engine": engine, "is_estimate": estimate, "data": data}
