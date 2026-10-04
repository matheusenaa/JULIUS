"""Medição de desempenho com volume grande (não roda no pytest normal).

    python -m tests.perf_check  (dentro de backend/)

Cria ~20 mil lançamentos (≈ 10 anos de uso intenso) e mede as rotas mais usadas.
"""

import os
import random
import tempfile
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

tmp = Path(tempfile.mkdtemp())
os.environ.update(
    APP_ENV="test",
    DATABASE_URL=f"sqlite:///{(tmp / 'perf.db').as_posix()}",
    AI_PROVIDER="none",
    REGISTER_LIMIT_PER_HOUR="1000",
    AI_LIMIT_PER_MINUTE="100000",
    TIMEZONE="local",
)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import insert  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Transaction  # noqa: E402

BACKEND = Path(__file__).resolve().parent.parent


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.attributes["database_url"] = url
    return cfg


class Api:
    def __init__(self, client: TestClient):
        self.c = client
        self.c.get("/api/health")

    def get(self, url):
        return self.c.get(url)

    def post(self, url, json=None):
        return self.c.post(url, json=json, headers={"x-csrf-token": self.c.cookies.get("julius_csrf", "")})


N = 20_000


def main() -> None:
    command.upgrade(alembic_config(os.environ["DATABASE_URL"]), "head")
    api = Api(TestClient(app))
    api.post("/api/auth/register", {"email": "perf@t.com", "name": "Perf", "password": "senha-forte-123"})
    acc = api.post(
        "/api/accounts", {"name": "Banco", "kind": "checking", "initial_balance_cents": 10_000_00}
    ).json()
    card = api.post(
        "/api/accounts", {"name": "Cartão", "kind": "credit_card", "closing_day": 5, "due_day": 12}
    ).json()
    cats = [c["id"] for c in api.get("/api/categories").json() if c["kind"] == "expense"]
    user_id = api.get("/api/auth/me").json()["id"]
    today = date.today()
    rows = []
    for i in range(N):
        on_card = i % 4 == 0
        d = today - timedelta(days=random.randint(0, 3650))
        rows.append(
            {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "account_id": card["id"] if on_card else acc["id"],
                "type": "income" if i % 15 == 0 else "expense",
                "status": "paid",
                "amount_cents": random.randint(500, 50000),
                "occurred_on": d,
                "description": f"Lançamento {i}",
                "category_id": None if i % 15 == 0 else random.choice(cats),
                "is_fixed": False,
                "source": "import",
                "version": 1,
                "invoice_month": d.replace(day=1) if on_card else None,
            }
        )
    with SessionLocal() as db:
        db.execute(insert(Transaction), rows)
        db.commit()
    for i in range(5):
        api.post(
            "/api/recurrences",
            {
                "type": "expense",
                "account_id": acc["id"],
                "description": f"Conta {i}",
                "amount_cents": 10000,
                "start_date": today.isoformat(),
                "day_of_month": 10,
            },
        )
    routes = [
        "/api/dashboard",
        "/api/overview",
        "/api/timeline?days=90",
        "/api/transactions",
        "/api/transactions?q=Lan%C3%A7amento%201",
        "/api/reports?period=month",
        "/api/reports?period=year",
        "/api/accounts",
        f"/api/accounts/{card['id']}/invoices",
    ]
    if os.environ.get("PERF_EXPLAIN"):
        from sqlalchemy import case, func, select, text

        from app.services.ledger import _active_tx

        signed = case(
            (Transaction.type == "income", Transaction.amount_cents), else_=-Transaction.amount_cents
        )
        q = (
            select(Transaction.account_id, func.sum(signed))
            .where(*_active_tx(user_id), Transaction.status == "paid", Transaction.occurred_on <= today)
            .group_by(Transaction.account_id)
        )
        with SessionLocal() as db:
            sql = str(q.compile(db.bind, compile_kwargs={"literal_binds": True}))
            for row in db.execute(text("EXPLAIN QUERY PLAN " + sql)):
                print("PLAN", row)
            t = time.perf_counter()
            db.execute(q).all()
            print(f"query: {(time.perf_counter() - t) * 1000:.0f} ms")
        return
    profile = os.environ.get("PERF_PROFILE")
    if profile:
        import cProfile
        import pstats

        api.get(profile)
        pr = cProfile.Profile()
        pr.enable()
        api.get(profile)
        pr.disable()
        pstats.Stats(pr).sort_stats("cumulative").print_stats(r"app[\\/]", 25)
        return
    print(f"{N} lançamentos. Tempo por rota (média de 3):")
    for r in routes:
        api.get(r)  # aquecimento
        t = time.perf_counter()
        for _ in range(3):
            assert api.get(r).status_code == 200, r
        print(f"  {r:45s} {(time.perf_counter() - t) / 3 * 1000:7.0f} ms")


if __name__ == "__main__":
    main()
