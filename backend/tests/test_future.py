"""Lançamentos futuros, status, linha do tempo, dívidas e visão geral."""

from datetime import date, timedelta

from app.services.dates import add_months

TODAY = date.today()


def d(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


def account(api, **kw):
    r = api.post("/api/accounts", {"name": "Corrente", "kind": "checking", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def tx(api, **kw):
    body = {"type": "expense", "occurred_on": TODAY.isoformat(), "description": "x", **kw}
    r = api.post("/api/transactions", body)
    assert r.status_code == 201, r.text
    return r.json()


def test_briefing_future_vision(api, ids):
    """Saldo 2.500 + salário 3.200 − aluguel 1.200 − cartão 800 − internet 100 − parcela 250 = 3.350."""
    acc = account(api, initial_balance_cents=250000)
    api.post(
        "/api/recurrences",
        {
            "type": "income",
            "account_id": acc["id"],
            "description": "Salário",
            "amount_cents": 320000,
            "start_date": d(1),
            "day_of_month": (TODAY + timedelta(days=1)).day,
        },
    )
    tx(
        api,
        account_id=acc["id"],
        description="Aluguel",
        amount_cents=120000,
        occurred_on=d(2),
        status="pending",
    )
    card = api.post(
        "/api/accounts", {"name": "Cartão", "kind": "credit_card", "closing_day": 1, "due_day": 10}
    ).json()
    tx(
        api,
        account_id=card["id"],
        description="Compras",
        amount_cents=80000,
        occurred_on=add_months(TODAY, -1).replace(day=15).isoformat(),
    )
    tx(
        api,
        account_id=acc["id"],
        description="Internet",
        amount_cents=10000,
        occurred_on=d(4),
        status="confirmed",
    )
    api.post(
        "/api/debts",
        {
            "name": "Notebook",
            "original_cents": 300000,
            "installments_total": 12,
            "installment_cents": 25000,
            "installments_paid_before": 5,
            "first_due_date": add_months(TODAY + timedelta(days=5), -5).isoformat(),
            "account_id": acc["id"],
        },
    )

    tl = api.get("/api/timeline", params={"days": 6}).json()
    names = [e["description"] for e in tl["events"]]
    assert "Salário" in names and "Aluguel" in names and "Internet" in names
    assert any(n.startswith("Fatura Cartão") for n in names)
    assert any(n.startswith("Notebook (6/12)") for n in names)
    assert tl["start_balance_cents"] == 250000
    assert tl["end_balance_cents"] == 335000
    # Saldo depois de cada evento é cumulativo e calculado pelo sistema
    running = tl["start_balance_cents"]
    for e in tl["events"]:
        running += e["amount_cents"] if e["flow"] == "in" else -e["amount_cents"]
        assert e["balance_after"] == running


def test_status_rules(api):
    acc = account(api, initial_balance_cents=100000)
    p = tx(api, account_id=acc["id"], amount_cents=1000, occurred_on=d(3), status="pending")
    c = tx(api, account_id=acc["id"], amount_cents=2000, occurred_on=d(3), status="confirmed")
    x = tx(api, account_id=acc["id"], amount_cents=4000, occurred_on=d(3), status="pending")
    late = tx(
        api,
        account_id=acc["id"],
        amount_cents=500,
        occurred_on=d(-3),
        status="pending",
        description="Atrasada",
    )
    assert (
        api.patch(f"/api/transactions/{x['id']}", {"version": x["version"], "status": "canceled"}).status_code
        == 200
    )

    tl = api.get("/api/timeline", params={"days": 10}).json()
    ids = {e["ref_id"]: e for e in tl["events"]}
    assert p["id"] in ids and c["id"] in ids and x["id"] not in ids  # cancelado não entra
    assert ids[late["id"]]["status"] == "overdue"  # atrasado é calculado
    assert ids[late["id"]]["effective"] == TODAY.isoformat()  # e entra "hoje" na projeção
    assert tl["end_balance_cents"] == 100000 - 1000 - 2000 - 500

    # Pagar: previsto → pago. Saldo atual muda só quando realizado
    acct = lambda: next(a for a in api.get("/api/accounts").json() if a["id"] == acc["id"])  # noqa: E731
    assert acct()["balance_cents"] == 100000
    api.patch(
        f"/api/transactions/{late['id']}",
        {"version": late["version"], "status": "paid", "occurred_on": TODAY.isoformat()},
    )
    assert acct()["balance_cents"] == 99500
    # Lista mostra o cancelado mas não soma
    page = api.get("/api/transactions", params={"account_id": acc["id"]}).json()
    assert page["total"] == 4 and page["expense_cents"] == 1000 + 2000 + 500


def test_salary_predicted_then_received(api, ids):
    acc = account(api)
    rec = api.post(
        "/api/recurrences",
        {
            "type": "income",
            "account_id": acc["id"],
            "description": "Salário",
            "amount_cents": 320000,
            "start_date": TODAY.isoformat(),
            "day_of_month": TODAY.day,
            "category_id": ids["cats"]["Salário"],
        },
    ).json()
    dash = api.get("/api/dashboard").json()
    assert dash["month"]["income_cents"] == 0  # previsão não é dinheiro recebido
    assert any(u["description"] == "Salário" for u in dash["upcoming"])
    api.post(f"/api/recurrences/{rec['id']}/confirm", {"occurrence_date": TODAY.isoformat()})
    dash = api.get("/api/dashboard").json()
    assert dash["month"]["income_cents"] == 320000
    assert not any(u["description"] == "Salário" and u["date"] == TODAY.isoformat() for u in dash["upcoming"])


def test_debt_calculations_and_payment(api, ids):
    acc = account(api, initial_balance_cents=100000)
    first = add_months(TODAY, -4)  # 5 parcelas já venceram (meses -4..0)
    r = api.post(
        "/api/debts",
        {
            "name": "Notebook",
            "creditor": "Loja X",
            "original_cents": 300000,
            "installments_total": 12,
            "installment_cents": 25000,
            "installments_paid_before": 5,
            "first_due_date": first.isoformat(),
            "account_id": acc["id"],
            "category_id": ids["cats"]["Eletrônicos"],
        },
    )
    assert r.status_code == 201, r.text
    debt = r.json()
    assert debt["remaining_installments"] == 7
    assert debt["remaining_cents"] == 175000
    assert debt["next_due"] == add_months(first, 5).isoformat()
    assert debt["end_date"] == add_months(first, 11).isoformat()

    paid = api.post(f"/api/debts/{debt['id']}/pay", {}).json()
    assert paid["transaction"]["description"] == "Notebook (6/12)"
    assert paid["transaction"]["amount_cents"] == 25000
    assert paid["debt"]["remaining_installments"] == 6 and paid["debt"]["remaining_cents"] == 150000
    acc_after = next(a for a in api.get("/api/accounts").json() if a["id"] == acc["id"])
    assert acc_after["balance_cents"] == 75000

    # Excluir o pagamento devolve a parcela
    api.delete(f"/api/transactions/{paid['transaction']['id']}")
    back = next(x for x in api.get("/api/debts").json() if x["id"] == debt["id"])
    assert back["remaining_installments"] == 7
    # Pagar de novo reaproveita a mesma parcela (sem violar unicidade)
    again = api.post(f"/api/debts/{debt['id']}/pay", {})
    assert again.status_code == 201 and again.json()["transaction"]["debt_installment"] == 6


def test_debt_paid_off_and_validation(api):
    acc = account(api)
    r = api.post(
        "/api/debts",
        {
            "name": "Empréstimo",
            "original_cents": 1000,
            "installments_total": 2,
            "installment_cents": 500,
            "installments_paid_before": 3,
            "first_due_date": TODAY.isoformat(),
        },
    )
    assert r.status_code == 422
    debt = api.post(
        "/api/debts",
        {
            "name": "Empréstimo",
            "original_cents": 1000,
            "installments_total": 2,
            "installment_cents": 500,
            "installments_paid_before": 1,
            "first_due_date": TODAY.isoformat(),
            "account_id": acc["id"],
        },
    ).json()
    assert api.post(f"/api/debts/{debt['id']}/pay", {}).status_code == 201
    done = api.get("/api/debts").json()[0]
    assert done["situation"] == "quitada" and done["remaining_cents"] == 0
    assert api.post(f"/api/debts/{debt['id']}/pay", {}).status_code == 409


def test_overview_payload(api, ids):
    acc = account(api, initial_balance_cents=50000)
    tx(api, account_id=acc["id"], amount_cents=1000, category_id=ids["cats"]["Mercado"])
    tx(
        api,
        account_id=acc["id"],
        amount_cents=70000,
        occurred_on=d(3),
        status="pending",
        description="Conta grande",
    )
    ov = api.get("/api/overview").json()
    k = ov["kpis"]
    assert k["balance_cents"] == 49000
    assert k["to_pay_cents"] == 70000
    assert ov["projection"][0]["balance_cents"] == 49000
    assert ov["projection"][-1]["balance_cents"] == -21000
    assert len(ov["history"]) == 90 and ov["history"][-1]["balance_cents"] == 49000
    assert ov["history"][-2]["balance_cents"] == 50000  # ontem, antes do gasto de hoje
    assert any("negativo" in a["text"] for a in ov["alerts"])
    cal = {c["date"]: c for c in ov["calendar"]}
    assert cal[TODAY.isoformat()]["out_cents"] == 1000


def test_alerts_due_tomorrow_and_week(api):
    acc = account(api, initial_balance_cents=500000)
    tx(
        api,
        account_id=acc["id"],
        amount_cents=120000,
        occurred_on=d(1),
        status="pending",
        description="Aluguel",
    )
    texts = [i["text"] for i in api.get("/api/dashboard").json()["insights"]]
    assert any("Aluguel: vence amanhã" in t for t in texts)
    assert any("próximos 7 dias" in t for t in texts)


def test_request_cache_never_returns_stale_balance(api):
    """Na MESMA sessão: calcula, grava, calcula de novo — o segundo cálculo vê a gravação."""
    from app.db import SessionLocal
    from app.models import User
    from app.schemas import TransactionIn
    from app.services import ledger
    from app.services import transactions as tx_svc

    acc = account(api, initial_balance_cents=10000)
    user_id = api.get("/api/auth/me").json()["id"]
    with SessionLocal() as db:
        assert db.get(User, user_id) is not None
        before = ledger.account_balances(db, user_id, as_of=TODAY)[acc["id"]]
        tx_svc.create(
            db,
            user_id,
            TransactionIn(
                type="expense",
                account_id=acc["id"],
                amount_cents=2500,
                occurred_on=TODAY,
                description="cache",
            ),
        )
        after = ledger.account_balances(db, user_id, as_of=TODAY)[acc["id"]]
    assert (before, after) == (10000, 7500)
