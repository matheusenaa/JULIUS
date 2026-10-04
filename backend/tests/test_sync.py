"""Sincronização: instalação local (banco próprio) ↔ servidor online (outro banco)."""

import uuid
from datetime import date

import httpx
import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.db import make_engine
from app.main import app
from app.models import Category, SyncConflict, Transaction, User
from app.schemas import TransactionIn, TransactionUpdate
from app.services import auth as auth_svc
from app.services import transactions as tx_svc
from app.services.sync_client import SyncClient, SyncError
from tests.conftest import Api, alembic_config

PASSWORD = "senha-forte-123"


@pytest.fixture
def setup(tmp_path, anon):
    """Servidor online (app de teste) + instalação local com banco separado."""
    email = f"sync-{uuid.uuid4().hex[:6]}@t.com"
    assert anon.post("/api/auth/register", {"email": email, "name": "Ana", "password": PASSWORD}).status_code == 201
    url = f"sqlite:///{(tmp_path / 'local.db').as_posix()}"
    command.upgrade(alembic_config(url), "head")
    engine = make_engine(url)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    local_user = auth_svc.register(db, email, "Ana", PASSWORD)
    acc = tx_svc.get_owned(db, auth_svc.Account, db.scalar(select(auth_svc.Account.id)), local_user.id, "Conta")
    remote_http = TestClient(app, base_url="http://testserver")
    yield {"db": db, "user": local_user, "acc": acc, "remote": anon, "http": remote_http, "email": email}
    db.close()
    engine.dispose()


def local_tx(s, cents, desc="Café"):
    # A conta pode ter sido unida à do servidor no vínculo: busca a atual
    acc_id = s["db"].scalar(select(auth_svc.Account.id).where(
        auth_svc.Account.user_id == s["user"].id, auth_svc.Account.deleted_at.is_(None)))
    return tx_svc.create(s["db"], s["user"].id, TransactionIn(
        type="expense", account_id=acc_id, amount_cents=cents, occurred_on=date.today(), description=desc))


def client(s):
    return SyncClient(s["db"], s["db"].get(User, s["user"].id), http=s["http"])


def remote_items(s, q):
    return s["remote"].get("/api/transactions", params={"q": q}).json()["items"]


def test_link_merges_defaults_and_uploads_local_data(setup):
    s = setup
    tx = local_tx(s, 450, "Pão de queijo")
    result = client(s).link("http://testserver", s["email"], PASSWORD)
    assert result["pushed"]["applied"] >= 1 and result["conflicts"] == 0

    remote = remote_items(s, "Pão de queijo")
    assert len(remote) == 1 and remote[0]["id"] == tx.id  # mesmo UUID nos dois lados
    # Categorias padrão unidas: nenhuma duplicada no servidor nem no local
    remote_cats = s["remote"].get("/api/categories").json()
    assert len({(c["name"], c["kind"], c["parent_id"] is None) for c in remote_cats}) == len(remote_cats)
    local_count = s["db"].scalar(select(func.count()).select_from(Category).where(
        Category.user_id == s["user"].id, Category.deleted_at.is_(None)))
    assert local_count == len(remote_cats)
    # A conta "Carteira" padrão também foi unida (o lançamento aponta para a conta do servidor)
    accounts = s["remote"].get("/api/accounts").json()
    assert [a["name"] for a in accounts].count("Carteira") == 1
    assert remote[0]["account_id"] == accounts[0]["id"]


def test_changes_flow_both_ways(setup):
    s = setup
    c = client(s)
    c.link("http://testserver", s["email"], PASSWORD)
    # Celular/web altera no servidor → computador recebe
    acc_id = s["remote"].get("/api/accounts").json()[0]["id"]
    created = s["remote"].post("/api/transactions", {"type": "expense", "account_id": acc_id, "amount_cents": 9900,
                                                     "occurred_on": date.today().isoformat(), "description": "Internet"})
    c.sync()
    local = s["db"].get(Transaction, created.json()["id"])
    assert local is not None and local.amount_cents == 9900 and local.synced_version == local.version
    # Computador altera → servidor recebe
    tx_svc.update(s["db"], s["user"].id, local.id, TransactionUpdate(version=local.version, amount_cents=10500))
    stats = c.sync()
    assert stats["pushed"]["applied"] == 1
    assert remote_items(s, "Internet")[0]["amount_cents"] == 10500
    # Sem mudanças: nada é reenviado
    assert c.sync()["pushed"]["sent"] == 0


def test_conflict_is_never_silently_overwritten(setup):
    """Computador: R$ 100 → R$ 110. Celular: mesma despesa → R$ 120. O usuário decide."""
    s = setup
    c = client(s)
    tx = local_tx(s, 10000, "Despesa disputada")
    c.link("http://testserver", s["email"], PASSWORD)
    tx = s["db"].get(Transaction, tx.id)

    server_tx = remote_items(s, "disputada")[0]
    s["remote"].patch(f"/api/transactions/{tx.id}", {"version": server_tx["version"], "amount_cents": 12000})
    tx_svc.update(s["db"], s["user"].id, tx.id, TransactionUpdate(version=tx.version, amount_cents=11000))

    stats = c.sync()
    assert stats["conflicts"] == 1
    assert s["db"].get(Transaction, tx.id).amount_cents == 11000  # local preservado
    assert remote_items(s, "disputada")[0]["amount_cents"] == 12000  # servidor preservado

    conflict = s["db"].scalar(select(SyncConflict).where(SyncConflict.resolved_at.is_(None)))
    assert conflict.local_data["amount_cents"] == 11000 and conflict.remote_data["amount_cents"] == 12000
    c.resolve(conflict, "local")
    c.sync()
    assert remote_items(s, "disputada")[0]["amount_cents"] == 11000
    assert c.sync()["conflicts"] == 0


def test_conflict_resolved_with_server_version(setup):
    s = setup
    c = client(s)
    tx = local_tx(s, 5000, "Outra disputa")
    c.link("http://testserver", s["email"], PASSWORD)
    tx = s["db"].get(Transaction, tx.id)
    server_tx = remote_items(s, "Outra disputa")[0]
    s["remote"].patch(f"/api/transactions/{tx.id}", {"version": server_tx["version"], "amount_cents": 7000})
    tx_svc.update(s["db"], s["user"].id, tx.id, TransactionUpdate(version=tx.version, amount_cents=6000))
    c.sync()
    conflict = s["db"].scalar(select(SyncConflict).where(SyncConflict.resolved_at.is_(None)))
    c.resolve(conflict, "remote")
    assert s["db"].get(Transaction, tx.id).amount_cents == 7000
    assert c.sync()["pushed"]["sent"] == 0


def test_delete_propagates(setup):
    s = setup
    c = client(s)
    tx = local_tx(s, 300, "Para apagar")
    c.link("http://testserver", s["email"], PASSWORD)
    tx_svc.delete(s["db"], s["user"].id, tx.id)
    c.sync()
    assert remote_items(s, "Para apagar") == []


def test_offline_keeps_local_data_and_reports(setup):
    s = setup
    c = client(s)
    c.link("http://testserver", s["email"], PASSWORD)
    local_tx(s, 777, "Feito sem internet")

    def offline(request):
        raise httpx.ConnectError("sem rede")

    c.http = httpx.Client(transport=httpx.MockTransport(offline), base_url="http://testserver")
    with pytest.raises(SyncError):
        c.sync()
    assert s["db"].scalar(select(func.count()).select_from(Transaction).where(
        Transaction.description == "Feito sem internet")) == 1
    status_error = c.state.last_error
    assert status_error and "conexão" in status_error.lower()
    # Internet volta: o pendente é enviado
    c.http = s["http"]
    assert c.sync()["pushed"]["applied"] >= 1
    assert len(remote_items(s, "Feito sem internet")) == 1


def test_server_rejects_foreign_references(setup, anon):
    s = setup
    other = Api(TestClient(app))
    other.post("/api/auth/register", {"email": f"x{uuid.uuid4().hex[:5]}@t.com", "name": "X", "password": PASSWORD})
    foreign_acc = other.get("/api/accounts").json()[0]["id"]
    r = s["remote"].post("/api/sync/push", {"changes": [{"entity": "transactions", "id": str(uuid.uuid4()),
                                                         "base_version": None, "data": {
        "account_id": foreign_acc, "type": "expense", "status": "paid", "amount_cents": 100,
        "occurred_on": date.today().isoformat(), "description": "invasão", "source": "manual"}}]})
    assert r.json()["results"][0]["status"] == "rejected"
