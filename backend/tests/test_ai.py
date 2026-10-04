from datetime import date, timedelta

import pytest

from app.ai import nlp_pt
from app.ai.providers import AIUnavailable, set_provider_for_tests
from app.services.dates import add_months, month_start

TODAY = date.today()


def parse(api, text):
    r = api.post("/api/quick-input/parse", {"text": text})
    assert r.status_code == 200, r.text
    return r.json()


def cat_name(ids, cat_id):
    return next((n for n, i in ids["cats"].items() if i == cat_id), None)


# ---------- Parser local (unidade) ----------
@pytest.mark.parametrize(
    ("text", "cents"),
    [
        ("gastei 45 reais no mercado", 4500),
        ("R$ 1.200,50 no notebook", 120050),
        ("1.200 em 12x", 120000),
        ("almoço 32,90", 3290),
        ("paguei 2 mil de aluguel", 200000),
        ("vou receber 500 dia 10", 50000),
        ("dia 5 paguei 80 de luz", 8000),
        ("compra 10/09 de 59.90", 5990),
    ],
)
def test_amount_extraction(text, cents):
    assert nlp_pt.extract_amount(text) == cents


def test_no_amount():
    assert nlp_pt.extract_amount("gastei no mercado") is None


# ---------- Exemplos do briefing ----------
def test_briefing_examples(api, ids):
    cases = {
        "gastei 45 reais no mercado": ("expense", 4500, "Mercado"),
        "abasteci o carro com 120 reais": ("expense", 12000, "Combustível"),
        "recebi meu salário de 3200": ("income", 320000, "Salário"),
        "paguei 850 de aluguel": ("expense", 85000, "Aluguel"),
        "comprei uma camisa por 150": ("expense", 15000, "Roupas"),
        "gastei 80 no lazer": ("expense", 8000, "Lazer"),
        "paguei 150 reais no posto": ("expense", 15000, "Combustível"),
        "gastei 50 no almoço": ("expense", 5000, "Restaurantes"),
    }
    for text, (tx_type, cents, category) in cases.items():
        p = parse(api, text)
        assert p["type"] == tx_type, text
        assert p["amount_cents"] == cents, text
        assert cat_name(ids, p["category_id"]) == category, text
        assert p["occurred_on"] == TODAY.isoformat()
        assert p["status"] == "paid"
        assert p["account_id"]


def test_future_income_is_pending(api):
    p = parse(api, "vou receber 500 dia 10")
    assert p["type"] == "income" and p["amount_cents"] == 50000
    assert p["status"] == "pending"
    assert date.fromisoformat(p["occurred_on"]).day == 10
    assert date.fromisoformat(p["occurred_on"]) >= TODAY


def test_monthly_bill_suggests_recurrence(api, ids):
    p = parse(api, "minha conta de internet é 100 por mês")
    assert p["amount_cents"] == 10000
    assert cat_name(ids, p["category_id"]) == "Internet"
    assert p["recurrence"]["frequency"] == "monthly"
    assert p["is_fixed"] is True


def test_installments_and_card(api):
    card = api.post(
        "/api/accounts", {"name": "Nubank", "kind": "credit_card", "closing_day": 3, "due_day": 10}
    ).json()
    p = parse(api, "comprei um notebook de 1.200 em 12x no nubank")
    assert p["installments"] == 12
    assert p["amount_cents"] == 120000
    assert p["account_id"] == card["id"]
    assert p["payment_method"] == "credit"


def test_yesterday(api):
    p = parse(api, "ontem gastei 30 no uber")
    assert p["occurred_on"] == (TODAY - timedelta(days=1)).isoformat()


def test_transfer_between_accounts(api):
    poup = api.post("/api/accounts", {"name": "Poupança", "kind": "savings"}).json()
    p = parse(api, "transferi 300 para poupança")
    assert p["type"] == "transfer"
    assert p["to_account_id"] == poup["id"]
    assert p["account_id"] != poup["id"]
    assert p["category_id"] is None


def test_missing_amount_reported(api):
    p = parse(api, "gastei no mercado")
    assert p["amount_cents"] is None
    assert "amount_cents" in p["missing"]


def test_parsed_proposal_can_be_saved(api):
    p = parse(api, "gastei 45 reais no mercado")
    body = {
        k: p[k]
        for k in (
            "type",
            "amount_cents",
            "occurred_on",
            "description",
            "category_id",
            "account_id",
            "payment_method",
            "status",
            "is_fixed",
        )
    }
    r = api.post("/api/transactions", {**body, "source": "quick_input"})
    assert r.status_code == 201


def test_confirmed_correction_teaches_categorizer(api, ids):
    p = parse(api, "40 na lojinha do bairro")
    assert p["category_id"] is None
    body = {k: p[k] for k in ("type", "amount_cents", "occurred_on", "account_id")}
    r = api.post(
        "/api/transactions",
        {**body, "description": "Lojinha do bairro", "category_id": ids["cats"]["Casa"], "source": "quick_input"},
    )
    assert r.status_code == 201
    assert parse(api, "25 na lojinha")["category_id"] == ids["cats"]["Casa"]


# ---------- IA: validação e falhas ----------
class FakeAI:
    name = "fake"

    def __init__(self, response=None, fail=False):
        self.response, self.fail, self.calls = response, fail, 0

    def generate_json(self, system, prompt, image=None, mime=None):
        self.calls += 1
        if self.fail:
            raise AIUnavailable("offline")
        return self.response(prompt) if callable(self.response) else self.response


@pytest.fixture
def fake_ai():
    holder = {}

    def install(**kw):
        holder["ai"] = FakeAI(**kw)
        set_provider_for_tests(holder["ai"])
        return holder["ai"]

    yield install
    set_provider_for_tests(None)


def test_ai_failure_falls_back_to_local(api, ids, fake_ai):
    ai = fake_ai(fail=True)
    p = parse(api, "gastei 45 reais no mercado")
    assert ai.calls == 1
    assert p["ai_error"] is True and p["engine"] == "local"
    assert p["amount_cents"] == 4500 and cat_name(ids, p["category_id"]) == "Mercado"


def test_ai_invalid_ids_and_amount_are_ignored(api, ids, fake_ai):
    fake_ai(
        response={
            "type": "expense",
            "amount": 999999,
            "category_id": "id-inventado",
            "account_id": "conta-falsa",
            "description": "Supermercado",
        }
    )
    p = parse(api, "gastei 45 reais no mercado")
    assert p["amount_cents"] == 4500  # valor do parser determinístico prevalece
    assert cat_name(ids, p["category_id"]) == "Mercado"
    assert p["account_id"] in ids["accounts"].values()
    assert p["description"] == "Supermercado"
    assert p["engine"] == "ai"


def test_ai_valid_category_used(api, ids, fake_ai):
    fake_ai(
        response={
            "type": "expense",
            "category_id": ids["cats"]["Presentes"],
            "description": "Presente da Ana",
        }
    )
    p = parse(api, "lembrancinha 40 reais")
    assert cat_name(ids, p["category_id"]) == "Presentes"


def test_assistant_never_takes_numbers_from_ai(api, fake_ai):
    acc = api.post(
        "/api/accounts", {"name": "Banco", "kind": "checking", "initial_balance_cents": 100000}
    ).json()
    fake_ai(response={"intent": "balance", "answer": "Você tem R$ 1.000.000,00"})
    r = api.post("/api/assistant/ask", {"question": "quanto tenho disponível?"}).json()
    assert "1.000,00" in r["answer"] and "1.000.000" not in r["answer"]
    assert r["data"]["accounts"][acc["id"]] == 100000


# ---------- Assistente: perguntas do briefing ----------
def _seed(api, ids):
    acc = api.post(
        "/api/accounts", {"name": "Banco", "kind": "checking", "initial_balance_cents": 500000}
    ).json()

    def add(cents, cat, when, tx_type="expense"):
        r = api.post(
            "/api/transactions",
            {
                "type": tx_type,
                "account_id": acc["id"],
                "amount_cents": cents,
                "occurred_on": when.isoformat(),
                "description": cat,
                "category_id": ids["cats"][cat],
            },
        )
        assert r.status_code == 201, r.text

    add(15000, "Combustível", TODAY)
    add(5000, "Combustível", TODAY)
    add(8000, "Cinema", TODAY)
    for i in (1, 2, 3):
        m = add_months(month_start(TODAY), -i)
        add(300000, "Salário", m.replace(day=5), "income")
        add(100000, "Aluguel", m.replace(day=10))
        add(50000, "Mercado", m.replace(day=12))
    return acc


def ask(api, q):
    r = api.post("/api/assistant/ask", {"question": q})
    assert r.status_code == 200, r.text
    return r.json()


def test_assistant_briefing_questions(api, ids):
    _seed(api, ids)
    r = ask(api, "Quanto gastei com combustível este mês?")
    assert r["intent"] == "spent" and r["data"]["total_cents"] == 20000 and "R$ 200,00" in r["answer"]

    r = ask(api, "Qual foi minha maior categoria de gastos?")
    assert r["intent"] == "top_category" and "Transporte" in r["answer"]

    r = ask(api, "Quanto gasto por mês em média?")
    assert r["intent"] == "average" and r["data"]["expense_cents"] == 150000

    r = ask(api, "Quanto economizei nos últimos três meses?")
    assert r["intent"] == "savings" and "R$ 4.500,00" in r["answer"]

    r = ask(api, "Se eu continuar gastando assim, quanto terei disponível daqui a seis meses?")
    assert r["intent"] == "forecast" and r["is_estimate"] is True
    assert len(r["data"]["points"]) == 6 and "estimativa" in r["answer"].lower()

    r = ask(api, "Quanto ainda posso gastar este mês?")
    assert r["intent"] == "can_spend" and r["is_estimate"] is True

    r = ask(api, "Quanto tenho disponível?")
    assert r["intent"] == "balance"

    r = ask(api, "Quais despesas fixas tenho?")
    assert r["intent"] == "fixed"


def test_assistant_month_name(api, ids):
    _seed(api, ids)
    last = add_months(month_start(TODAY), -1)
    from app.services.dates import MONTHS_PT

    r = ask(api, f"Quanto gastei com mercado em {MONTHS_PT[last.month - 1]}?")
    assert r["data"]["total_cents"] == 50000


def test_assistant_says_when_no_data(api):
    r = ask(api, "Quanto economizei nos últimos três meses?")
    assert "não há" in r["answer"].lower()
    r = ask(api, "quanto terei daqui a 6 meses?")
    assert "ainda não consigo" in r["answer"].lower()


def test_assistant_unknown_question(api):
    r = ask(api, "qual a capital da frança?")
    assert r["intent"] == "unknown" and "Exemplos" in r["answer"]


def test_conversation_history(api):
    r = ask(api, "Quanto tenho disponível?")
    conv = api.get(f"/api/assistant/conversations/{r['conversation_id']}").json()
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]
