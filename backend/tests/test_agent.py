"""Agente de IA: ferramentas controladas, ações só com confirmação, falhas e privacidade."""

from datetime import date, timedelta

import pytest

from app.ai.providers import AIUnavailable, ChatReply, set_provider_for_tests

TODAY = date.today()


class ScriptedAgent:
    """Provedor falso que segue um roteiro de chamadas de ferramentas."""

    name = "fake"

    def __init__(self, script):
        self.script, self.seen = list(script), []

    def generate_json(self, *a, **kw):
        raise AIUnavailable("não usado")

    def chat(self, messages, tools):
        self.seen.append(messages)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        if isinstance(step, str):
            return ChatReply(text=step, tool_calls=[], raw_message={"role": "assistant", "content": step})
        calls = [{"id": f"c{i}", "name": n, "arguments": a} for i, (n, a) in enumerate(step)]
        raw = {"role": "assistant", "content": None, "tool_calls": [
            {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": "{}"}} for c in calls]}
        return ChatReply(text=None, tool_calls=calls, raw_message=raw)


@pytest.fixture
def agent():
    holder = {}

    def install(script):
        holder["p"] = ScriptedAgent(script)
        set_provider_for_tests(holder["p"])
        return holder["p"]

    yield install
    set_provider_for_tests(None)


def ask(api, q, conv=None):
    r = api.post("/api/assistant/ask", {"question": q, "conversation_id": conv})
    assert r.status_code == 200, r.text
    return r.json()


def seed(api, ids):
    acc = api.post("/api/accounts", {"name": "Banco", "kind": "checking", "initial_balance_cents": 100000}).json()
    api.post("/api/transactions", {"type": "expense", "account_id": acc["id"], "amount_cents": 50000,
                                   "occurred_on": TODAY.isoformat(), "description": "Mercado grande",
                                   "category_id": ids["cats"]["Mercado"]})
    return acc


def test_agent_reads_with_tools_and_answers(api, ids, agent):
    seed(api, ids)
    fake = agent([[("get_balance", {})], "Seu saldo disponível é R$ 500,00."])
    r = ask(api, "me explique minha situação")
    assert r["engine"] == "ai" and r["answer"] == "Seu saldo disponível é R$ 500,00."
    tool_msg = fake.seen[1][-1]
    assert tool_msg["role"] == "tool" and "R$ 500,00" in tool_msg["content"]  # número veio do sistema


def test_agent_write_requires_confirmation(api, ids, agent):
    acc = seed(api, ids)
    agent([[("create_transaction", {"type": "expense", "amount": 32.5, "description": "Farmácia",
                                    "category": "Farmácia"})], "Preparei o lançamento; confirme no botão."])
    r = ask(api, "registre por favor uma compra na farmácia de 32,50")
    assert len(r["actions"]) == 1 and r["actions"][0]["status"] == "pending"
    before = api.get("/api/transactions", params={"account_id": acc["id"]}).json()["total"]
    assert before == 1  # nada gravado antes da confirmação
    ok = api.post(f"/api/assistant/actions/{r['actions'][0]['id']}/confirm")
    assert ok.status_code == 200 and ok.json()["status"] == "confirmed"
    items = api.get("/api/transactions", params={"q": "Farmácia"}).json()["items"]
    assert items[0]["amount_cents"] == 3250 and items[0]["source"] == "ai"
    again = api.post(f"/api/assistant/actions/{r['actions'][0]['id']}/confirm")
    assert again.status_code == 409  # não executa duas vezes


def test_agent_delete_can_be_rejected(api, ids, agent):
    seed(api, ids)
    tx = api.get("/api/transactions").json()["items"][0]
    agent([[("delete_transaction", {"id": tx["id"]})], "Confirme se deseja excluir."])
    r = ask(api, "tire aquilo do mercado")
    action = r["actions"][0]
    assert "Excluir despesa de R$ 500,00" in action["summary"]
    api.post(f"/api/assistant/actions/{action['id']}/reject")
    assert api.get(f"/api/transactions/{tx['id']}").status_code == 200
    assert api.post(f"/api/assistant/actions/{action['id']}/confirm").status_code == 409


def test_agent_invalid_tool_args_return_error_to_model(api, ids, agent):
    seed(api, ids)
    fake = agent([[("create_transaction", {"type": "expense", "amount": -5, "description": "x"})],
                  [("get_transactions", {"category": "Inexistente"})], "Não consegui."])
    r = ask(api, "faça algo estranho")
    assert r["actions"] == []
    assert "error" in fake.seen[1][-1]["content"] and "Inexistente" in fake.seen[2][-1]["content"]


def test_agent_cannot_touch_other_users_data(api, anon, ids, agent):
    seed(api, ids)
    tx_id = api.get("/api/transactions").json()["items"][0]["id"]
    api.post("/api/auth/logout")
    anon.post("/api/auth/register", {"email": "outro-agent@t.com", "name": "B", "password": "senha-forte-123"})
    fake = agent([[("delete_transaction", {"id": tx_id})], "ok"])
    r = ask(anon, "dê um sumiço naquele registro")
    assert r["actions"] == [] and "não encontrado" in fake.seen[1][-1]["content"].lower()


def test_agent_failure_falls_back_to_rules(api, ids, agent):
    seed(api, ids)
    agent([AIUnavailable("timeout")])
    r = ask(api, "me dê uma dica para organizar")
    assert r["engine"] in ("rules", "ai") and r["answer"]  # nunca fica sem resposta


def test_known_questions_use_rules_without_ai_cost(api, ids, agent):
    seed(api, ids)
    fake = agent(["não deveria ser chamado"])
    r = ask(api, "Quanto tenho disponível?")
    assert r["engine"] == "rules" and fake.seen == []


def test_rules_delete_with_confirmation(api, ids):
    seed(api, ids)
    r = ask(api, "Apague aquela despesa de R$ 500.")
    assert "Deseja realmente excluir" in r["answer"] and len(r["actions"]) == 1
    tx_id = api.get("/api/transactions").json()["items"][0]["id"]
    api.post(f"/api/assistant/actions/{r['actions'][0]['id']}/confirm")
    assert api.get(f"/api/transactions/{tx_id}").status_code == 404


def test_rules_new_questions(api, ids):
    acc = seed(api, ids)
    api.post("/api/transactions", {"type": "expense", "account_id": acc["id"], "amount_cents": 20000,
                                   "occurred_on": (TODAY + timedelta(days=2)).isoformat(), "description": "Luz",
                                   "status": "pending"})
    api.post("/api/transactions", {"type": "income", "account_id": acc["id"], "amount_cents": 300000,
                                   "occurred_on": (TODAY + timedelta(days=3)).isoformat(), "description": "Salário",
                                   "status": "pending"})
    api.post("/api/debts", {"name": "Notebook", "original_cents": 300000, "installments_total": 12,
                            "installment_cents": 25000, "installments_paid_before": 5,
                            "first_due_date": TODAY.isoformat()})
    r = ask(api, "Quanto vou gastar até o final do mês?")
    assert r["intent"] == "month_spend" and "R$ 500,00" in r["answer"]
    r = ask(api, "Quanto vou receber?")
    assert r["intent"] == "to_receive" and "R$ 3.000,00" in r["answer"]
    r = ask(api, "Quanto devo?")
    assert r["intent"] == "debts" and "R$ 1.750,00" in r["answer"]
    r = ask(api, "Por que gastei mais este mês?")
    assert r["intent"] == "why_more"
    assert "Alimentação" in r["answer"]  # categorias somadas na principal


def test_user_can_disable_ai_and_clear_memory(api, ids, agent):
    seed(api, ids)
    fake = agent(["resposta da IA"])
    api.patch("/api/auth/me", {"ai_enabled": False})
    r = ask(api, "me dê uma dica")
    assert fake.seen == [] and r["engine"] == "rules"
    assert api.get("/api/ai/status").json()["enabled"] is False
    api.patch("/api/auth/me", {"ai_enabled": True})
    assert api.delete("/api/assistant/history").status_code == 204
    assert api.get("/api/assistant/conversations").json() == []
    assert api.delete("/api/assistant/learning").status_code == 204


def test_privacy_hides_descriptions_from_ai(api, ids, agent):
    seed(api, ids)
    api.patch("/api/auth/me", {"ai_share_descriptions": False})
    fake = agent([[("get_transactions", {})], "ok"])
    ask(api, "mostre minhas movimentações recentes de forma criativa")
    content = fake.seen[1][-1]["content"]
    assert "Mercado grande" not in content and "Mercado" in content
