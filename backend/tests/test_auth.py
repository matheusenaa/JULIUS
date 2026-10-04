def test_health(anon):
    r = anon.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_register_login_logout(anon):
    body = {"email": "Maria@Teste.com", "name": "Maria", "password": "senha-forte-123"}
    r = anon.post("/api/auth/register", body)
    assert r.status_code == 201
    assert r.json()["email"] == "maria@teste.com"
    assert "password_hash" not in r.json()

    assert anon.get("/api/auth/me").status_code == 200
    assert anon.post("/api/auth/logout").status_code == 204
    assert anon.get("/api/auth/me").status_code == 401

    r = anon.post("/api/auth/login", {"email": "maria@teste.com", "password": "senha-forte-123"})
    assert r.status_code == 200
    assert anon.get("/api/auth/me").json()["name"] == "Maria"


def test_duplicate_email(anon):
    body = {"email": "dup@teste.com", "name": "A", "password": "senha-forte-123"}
    assert anon.post("/api/auth/register", body).status_code == 201
    r = anon.post("/api/auth/register", body)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "email_taken"


def test_wrong_password_generic_message(anon):
    anon.post("/api/auth/register", {"email": "x@teste.com", "name": "X", "password": "senha-forte-123"})
    anon.post("/api/auth/logout")
    wrong = anon.post("/api/auth/login", {"email": "x@teste.com", "password": "errada-errada"})
    missing = anon.post("/api/auth/login", {"email": "nao@existe.com", "password": "errada-errada"})
    assert wrong.status_code == missing.status_code == 401
    # Mesma mensagem: não revela se o e-mail existe
    assert wrong.json() == missing.json()


def test_weak_password_rejected(anon):
    r = anon.post("/api/auth/register", {"email": "w@teste.com", "name": "W", "password": "123"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation"


def test_login_rate_limit(anon):
    for _ in range(8):
        anon.post("/api/auth/login", {"email": "rl@teste.com", "password": "qualquer-coisa"})
    r = anon.post("/api/auth/login", {"email": "rl@teste.com", "password": "qualquer-coisa"})
    assert r.status_code == 429


def test_csrf_required(anon):
    r = anon.c.post(
        "/api/auth/register",
        json={"email": "csrf@teste.com", "name": "C", "password": "senha-forte-123"},
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "csrf"


def test_protected_routes_require_login(anon):
    assert anon.get("/api/accounts").status_code == 401
    assert anon.get("/api/transactions").status_code == 401


def test_password_change_keeps_current_session(api):
    r = api.post(
        "/api/auth/password",
        {"current_password": "senha-forte-123", "new_password": "nova-senha-456"},
    )
    assert r.status_code == 204
    assert api.get("/api/auth/me").status_code == 200
    api.post("/api/auth/logout")
    assert api.post("/api/auth/login", {"email": api.email, "password": "nova-senha-456"}).status_code == 200


def test_security_headers(anon):
    r = anon.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "content-security-policy" in r.headers
