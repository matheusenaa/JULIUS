import os
import tempfile
import uuid
from pathlib import Path

# Banco de teste isolado — definido ANTES de importar a aplicação
_TMP = Path(tempfile.mkdtemp(prefix="julius-test-"))
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["AI_PROVIDER"] = "none"
os.environ["TIMEZONE"] = "local"  # os testes comparam com date.today() da máquina

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api.deps import CSRF_COOKIE, CSRF_HEADER  # noqa: E402
from app.security import ratelimit  # noqa: E402

BACKEND = Path(__file__).resolve().parent.parent


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.attributes["database_url"] = url
    return cfg


@pytest.fixture(scope="session", autouse=True)
def _migrated_db():
    command.upgrade(alembic_config(os.environ["DATABASE_URL"]), "head")
    yield


@pytest.fixture(autouse=True)
def _reset_limits():
    for limiter in (ratelimit.login_limiter, ratelimit.register_limiter, ratelimit.ai_limiter):
        limiter.reset()


class Api:
    """Cliente de teste que se comporta como o frontend (envia o token CSRF)."""

    def __init__(self, client: TestClient):
        self.c = client
        self.c.get("/api/health")  # recebe o cookie CSRF

    def _h(self):
        return {CSRF_HEADER: self.c.cookies.get(CSRF_COOKIE, "")}

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, json=None, **kw):
        return self.c.post(url, json=json, headers=self._h(), **kw)

    def put(self, url, json=None, **kw):
        return self.c.put(url, json=json, headers=self._h(), **kw)

    def patch(self, url, json=None, **kw):
        return self.c.patch(url, json=json, headers=self._h(), **kw)

    def delete(self, url, **kw):
        return self.c.delete(url, headers=self._h(), **kw)


@pytest.fixture
def anon():
    from app.main import app

    with TestClient(app) as client:
        yield Api(client)


@pytest.fixture
def api(anon):
    """Cliente já autenticado com um usuário novo."""
    email = f"user-{uuid.uuid4().hex[:8]}@teste.com"
    r = anon.post("/api/auth/register", {"email": email, "name": "Teste", "password": "senha-forte-123"})
    assert r.status_code == 201, r.text
    anon.email = email
    return anon


@pytest.fixture
def ids(api):
    """Atalhos para contas e categorias padrão do usuário."""
    accounts = {a["name"]: a["id"] for a in api.get("/api/accounts").json()}
    cats = {c["name"]: c["id"] for c in api.get("/api/categories").json()}
    return {"accounts": accounts, "cats": cats}
