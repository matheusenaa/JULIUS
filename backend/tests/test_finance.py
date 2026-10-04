"""Regras financeiras: saldo, transferências, parcelas, cartão, recorrências."""

import uuid
from datetime import date, timedelta

from app.services.cards import due_date, invoice_month_for, split_installments
from app.services.dates import add_months, month_start

TODAY = date.today()


def tx(api, **kw):
    body = {"type": "expense", "occurred_on": TODAY.isoformat(), "description": "teste", **kw}
    r = api.post("/api/transactions", body)
    assert r.status_code == 201, r.text
    return r.json()


def account(api, **kw):
    r = api.post("/api/accounts", {"name": "Banco", "kind": "checking", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def balance_of(api, account_id):
    return next(a for a in api.get("/api/accounts").json() if a["id"] == account_id)["balance_cents"]


# ---------- Unidade ----------
def test_split_installments_exact():
    assert split_installments(120000, 12) == [10000] * 12
    assert split_installments(10000, 3) == [3334, 3333, 3333]
    assert sum(split_installments(99999, 7)) == 99999


def test_local_today_uses_configured_timezone(monkeypatch):
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    from app.config import get_settings
    from app.services.dates import local_today

    monkeypatch.setattr(get_settings(), "timezone", "America/Sao_Paulo")
    assert local_today() == datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    monkeypatch.setattr(get_settings(), "timezone", "Pacific/Kiritimati")  # UTC+14
    assert local_today() == (datetime.now(UTC) + timedelta(hours=14)).date()


def test_add_months_clamps_day():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)


def test_card_invoice_rules():
    # Fecha dia 25: compra dia 24 entra na fatura do mês; dia 25 vai para o seguinte
    assert invoice_month_for(date(2026, 10, 24), 25) == date(2026, 10, 1)
    assert invoice_month_for(date(2026, 10, 25), 25) == date(2026, 11, 1)
    # Vence dia 5 (antes do fechamento) → mês seguinte ao fechamento
    assert due_date(date(2026, 10, 1), 25, 5) == date(2026, 11, 5)
    # Fecha dia 3, vence dia 10 → mesmo mês
    assert due_date(date(2026, 10, 1), 3, 10) == date(2026, 10, 10)
    # Fechamento dia 31 em fevereiro
    assert invoice_month_for(date(2026, 2, 28), 31) == date(2026, 3, 1)


# ---------- Saldo ----------
def test_briefing_balance_example(api):
    """Saldo inicial 2.000 → despesa 300 → 1.700 → receita 1.000 → 2.700."""
    acc = account(api, initial_balance_cents=200000)
    tx(api, account_id=acc["id"], amount_cents=30000)
    assert balance_of(api, acc["id"]) == 170000
    tx(api, account_id=acc["id"], amount_cents=100000, type="income")
    assert balance_of(api, acc["id"]) == 270000


def test_transfer_moves_money_without_income_or_expense(api):
    a = account(api, name="Corrente", initial_balance_cents=100000)
    b = account(api, name="Poupança", kind="savings")
    tx(api, type="transfer", account_id=a["id"], to_account_id=b["id"], amount_cents=40000)
    assert balance_of(api, a["id"]) == 60000
    assert balance_of(api, b["id"]) == 40000
    dash = api.get("/api/dashboard").json()
    assert dash["month"]["income_cents"] == 0
    assert dash["month"]["expense_cents"] == 0
    assert dash["balance_cents"] == 100000  # total não muda


def test_transfer_validation(api):
    a = account(api)
    r = api.post(
        "/api/transactions",
        {
            "type": "transfer",
            "account_id": a["id"],
            "to_account_id": a["id"],
            "amount_cents": 100,
            "occurred_on": TODAY.isoformat(),
            "description": "x",
        },
    )
    assert r.status_code == 422


def test_pending_and_future_do_not_affect_current_balance(api):
    acc = account(api, initial_balance_cents=50000)
    tx(api, account_id=acc["id"], amount_cents=10000, status="pending")
    tx(api, account_id=acc["id"], amount_cents=5000, occurred_on=(TODAY + timedelta(days=40)).isoformat())
    assert balance_of(api, acc["id"]) == 50000


def test_negative_or_zero_amount_rejected(api):
    acc = account(api)
    for cents in (0, -100):
        r = api.post(
            "/api/transactions",
            {
                "type": "expense",
                "account_id": acc["id"],
                "amount_cents": cents,
                "occurred_on": TODAY.isoformat(),
                "description": "x",
            },
        )
        assert r.status_code == 422


# ---------- Parcelamento e cartão ----------
def test_installments_1200_in_12x(api):
    acc = account(api, initial_balance_cents=0)
    first = tx(api, account_id=acc["id"], amount_cents=120000, installments=12, description="Notebook")
    assert first["installment_number"] == 1 and first["installment_total"] == 12
    items = api.get("/api/transactions", params={"q": "Notebook", "page_size": 50}).json()["items"]
    assert len(items) == 12
    assert {i["amount_cents"] for i in items} == {10000}
    assert sum(i["amount_cents"] for i in items) == 120000  # nunca 14.400
    dates = sorted(i["occurred_on"] for i in items)
    assert dates[0] == TODAY.isoformat()
    assert dates[-1] == add_months(TODAY, 11).isoformat()
    # Fora do cartão: só a parcela de hoje afeta o saldo atual
    assert balance_of(api, acc["id"]) == -10000


def test_credit_card_purchase_invoice_and_limit(api):
    card = account(
        api, name="Cartão", kind="credit_card", credit_limit_cents=500000, closing_day=25, due_day=5
    )
    tx(api, account_id=card["id"], amount_cents=120000, installments=12, description="Celular")
    out = next(a for a in api.get("/api/accounts").json() if a["id"] == card["id"])
    assert out["used_cents"] == 120000  # compra inteira consome o limite
    assert out["available_cents"] == 380000

    invoices = api.get(f"/api/accounts/{card['id']}/invoices").json()
    assert len(invoices) == 12
    assert all(i["total_cents"] == 10000 for i in invoices)
    expected_first = invoice_month_for(TODAY, 25)
    assert invoices[0]["invoice_month"] == expected_first.isoformat()
    assert invoices[1]["invoice_month"] == add_months(expected_first, 1).isoformat()

    # Pagar a fatura = transferência; não é despesa de novo
    checking = account(api, initial_balance_cents=100000)
    tx(
        api,
        type="transfer",
        account_id=checking["id"],
        to_account_id=card["id"],
        amount_cents=10000,
        description="Pagamento fatura",
    )
    invoices = api.get(f"/api/accounts/{card['id']}/invoices").json()
    assert invoices[0]["remaining_cents"] == 0
    assert invoices[1]["remaining_cents"] == 10000
    report = api.get("/api/reports", params={"period": "month"}).json()
    assert report["expense_cents"] == 10000  # só a parcela do mês (competência), sem o pagamento


def test_delete_remaining_installments(api):
    acc = account(api)
    first = tx(api, account_id=acc["id"], amount_cents=60000, installments=6, description="Curso")
    items = api.get("/api/transactions", params={"q": "Curso"}).json()["items"]
    third = next(i for i in items if i["installment_number"] == 3)
    r = api.delete(f"/api/transactions/{third['id']}", params={"scope": "plan"})
    assert r.json()["deleted"] == 4
    left = api.get("/api/transactions", params={"q": "Curso"}).json()["items"]
    assert sorted(i["installment_number"] for i in left) == [1, 2]
    assert first["id"] in {i["id"] for i in left}


# ---------- Recorrências ----------
def _rec(api, acc_id, **kw):
    body = {
        "type": "expense",
        "account_id": acc_id,
        "description": "Aluguel",
        "amount_cents": 120000,
        "start_date": month_start(TODAY).isoformat(),
        "day_of_month": 10,
        **kw,
    }
    r = api.post("/api/recurrences", body)
    assert r.status_code == 201, r.text
    return r.json()


def test_recurrence_projection_confirm_without_duplicates(api):
    acc = account(api, initial_balance_cents=500000)
    rec = _rec(api, acc["id"])
    occ = [o for o in api.get("/api/recurrences/occurrences").json() if o["recurrence_id"] == rec["id"]]
    assert occ, "deveria haver ocorrência prevista"
    when = occ[0]["date"]

    r = api.post(f"/api/recurrences/{rec['id']}/confirm", {"occurrence_date": when})
    assert r.status_code == 201
    assert r.json()["source"] == "recurrence" and r.json()["is_fixed"] is True

    again = api.post(f"/api/recurrences/{rec['id']}/confirm", {"occurrence_date": when})
    assert again.status_code == 409  # não duplica
    remaining = [
        o["date"] for o in api.get("/api/recurrences/occurrences").json() if o["recurrence_id"] == rec["id"]
    ]
    assert when not in remaining


def test_recurrence_skip_and_invalid_date(api):
    acc = account(api)
    rec = _rec(api, acc["id"], description="Internet", amount_cents=10000, day_of_month=15)
    bad = api.post(
        f"/api/recurrences/{rec['id']}/skip",
        {"occurrence_date": month_start(TODAY).replace(day=16).isoformat()},
    )
    assert bad.status_code == 400
    when = month_start(TODAY).replace(day=15).isoformat()
    assert api.post(f"/api/recurrences/{rec['id']}/skip", {"occurrence_date": when}).status_code == 204
    dates = [
        o["date"] for o in api.get("/api/recurrences/occurrences").json() if o["recurrence_id"] == rec["id"]
    ]
    assert when not in dates
    # Depois de pular, ainda é possível efetivar (desfaz o pulo)
    assert api.post(f"/api/recurrences/{rec['id']}/confirm", {"occurrence_date": when}).status_code == 201


def test_projection_includes_recurrences(api):
    acc = account(api, initial_balance_cents=300000)
    eom = add_months(month_start(TODAY), 1) - timedelta(days=1)
    _rec(
        api,
        acc["id"],
        description="Academia",
        amount_cents=10000,
        day_of_month=eom.day,
        start_date=eom.isoformat(),
    )
    proj = api.get("/api/dashboard").json()["projection"]
    assert proj["recurring_cents"] == -10000
    assert proj["projected_cents"] == proj["current_cents"] - 10000


# ---------- Edição, concorrência, sincronização ----------
def test_idempotent_create_with_client_id(api):
    acc = account(api)
    client_id = str(uuid.uuid4())
    a = tx(api, id=client_id, account_id=acc["id"], amount_cents=1000)
    r = api.post(
        "/api/transactions",
        {
            "id": client_id,
            "type": "expense",
            "account_id": acc["id"],
            "amount_cents": 1000,
            "occurred_on": TODAY.isoformat(),
            "description": "teste",
        },
    )
    assert r.status_code == 201 and r.json()["id"] == a["id"]
    assert api.get("/api/transactions", params={"account_id": acc["id"]}).json()["total"] == 1


def test_version_conflict(api):
    acc = account(api)
    t = tx(api, account_id=acc["id"], amount_cents=1000)
    ok = api.patch(f"/api/transactions/{t['id']}", {"version": 1, "amount_cents": 2000})
    assert ok.status_code == 200 and ok.json()["version"] == 2
    stale = api.patch(f"/api/transactions/{t['id']}", {"version": 1, "amount_cents": 3000})
    assert stale.status_code == 409
    assert stale.json()["error"]["details"]["current"]["amount_cents"] == 2000


def test_category_correction_is_audited_and_learned(api, ids):
    acc = account(api)
    t = tx(
        api,
        account_id=acc["id"],
        amount_cents=15000,
        description="Posto Shell",
        category_id=ids["cats"]["Outros"],
    )
    r = api.patch(f"/api/transactions/{t['id']}", {"version": 1, "category_id": ids["cats"]["Combustível"]})
    assert r.status_code == 200
    log = api.get("/api/audit", params={"entity_id": t["id"]}).json()
    assert any('de "Outros" para "Combustível"' in e["summary"] for e in log)
    parsed = api.post("/api/quick-input/parse", {"text": "50 no posto shell"}).json()
    assert parsed["category_id"] == ids["cats"]["Combustível"]


def test_category_kind_must_match(api, ids):
    acc = account(api)
    r = api.post(
        "/api/transactions",
        {
            "type": "expense",
            "account_id": acc["id"],
            "amount_cents": 100,
            "occurred_on": TODAY.isoformat(),
            "description": "x",
            "category_id": ids["cats"]["Salário"],
        },
    )
    assert r.status_code == 400


def test_soft_delete_and_restore(api):
    acc = account(api, initial_balance_cents=10000)
    t = tx(api, account_id=acc["id"], amount_cents=1000)
    api.delete(f"/api/transactions/{t['id']}")
    assert balance_of(api, acc["id"]) == 10000
    assert api.get(f"/api/transactions/{t['id']}").status_code == 404
    assert api.post(f"/api/transactions/{t['id']}/restore").status_code == 200
    assert balance_of(api, acc["id"]) == 9000


def test_filters(api, ids):
    acc = account(api)
    tx(
        api,
        account_id=acc["id"],
        amount_cents=4500,
        description="Mercado Extra",
        category_id=ids["cats"]["Mercado"],
        payment_method="pix",
    )
    tx(api, account_id=acc["id"], amount_cents=8000, description="Cinema", category_id=ids["cats"]["Cinema"])
    tx(
        api,
        account_id=acc["id"],
        amount_cents=320000,
        type="income",
        description="Salário",
        category_id=ids["cats"]["Salário"],
    )
    q = lambda **p: api.get("/api/transactions", params={"account_id": acc["id"], **p}).json()  # noqa: E731
    assert q()["total"] == 3
    assert q(category_id=ids["cats"]["Alimentação"])["total"] == 1  # inclui subcategorias
    assert q(payment_method="pix")["total"] == 1
    assert q(min_cents=5000, type="expense")["total"] == 1
    assert q(q="mercado")["total"] == 1
    assert q(q="100%")["total"] == 0  # caracteres curinga são escapados
    s = q()
    assert s["income_cents"] == 320000 and s["expense_cents"] == 12500


def test_users_are_isolated(api, anon):
    acc = account(api)
    t = tx(api, account_id=acc["id"], amount_cents=1000)
    api.post("/api/auth/logout")
    anon.post(
        "/api/auth/register",
        {"email": f"outro-{uuid.uuid4().hex[:6]}@t.com", "name": "B", "password": "senha-forte-123"},
    )
    assert anon.get(f"/api/transactions/{t['id']}").status_code == 404
    assert anon.patch(f"/api/transactions/{t['id']}", {"version": 1, "amount_cents": 1}).status_code == 404
    r = anon.post(
        "/api/transactions",
        {
            "type": "expense",
            "account_id": acc["id"],
            "amount_cents": 100,
            "occurred_on": TODAY.isoformat(),
            "description": "invasão",
        },
    )
    assert r.status_code == 404


def test_report_by_category_and_comparison(api, ids):
    acc = account(api)
    tx(api, account_id=acc["id"], amount_cents=10000, category_id=ids["cats"]["Combustível"])
    tx(api, account_id=acc["id"], amount_cents=5000, category_id=ids["cats"]["Uber/Táxi"])
    r = api.get("/api/reports", params={"period": "month"}).json()
    transporte = next(c for c in r["by_category"] if c["name"] == "Transporte")
    assert transporte["total_cents"] == 15000  # subcategorias somadas na principal
    assert r["previous"]["expense_cents"] == 0


def test_budget_and_goal(api, ids):
    acc = account(api)
    r = api.put("/api/budgets", {"category_id": ids["cats"]["Lazer"], "amount_cents": 10000})
    assert r.status_code == 200
    tx(api, account_id=acc["id"], amount_cents=9000, category_id=ids["cats"]["Cinema"])
    budget = next(b for b in api.get("/api/budgets").json() if b["name"] == "Lazer")
    assert budget["spent_cents"] == 9000 and budget["ratio"] == 0.9
    assert any("Lazer" in i["text"] for i in api.get("/api/dashboard").json()["insights"])

    g = api.post(
        "/api/goals",
        {
            "name": "Reserva",
            "target_cents": 1200000,
            "saved_cents": 200000,
            "target_date": add_months(TODAY, 10).isoformat(),
        },
    )
    assert g.status_code == 201
    assert g.json()["monthly_needed_cents"] == 100000
