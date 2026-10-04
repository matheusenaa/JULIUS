import json
import tempfile
from datetime import date
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect

from app.ai.providers import set_provider_for_tests
from tests.conftest import alembic_config

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 200


class ReceiptAI:
    name = "fake"

    def __init__(self, cat_id=None):
        self.cat_id = cat_id

    def generate_json(self, system, prompt, image=None, mime=None):
        assert image == JPEG and mime == "image/jpeg"
        return {
            "document_type": "cupom",
            "merchant": "Posto Ipiranga",
            "date": "2026-10-03",
            "total": 150.0,
            "direction": "expense",
            "payment_method": "debit",
            "items": ["Gasolina comum"],
            "legible": True,
        }


@pytest.fixture
def receipt_ai():
    set_provider_for_tests(ReceiptAI())
    yield
    set_provider_for_tests(None)


def upload(api, url, content, name="cupom.jpg"):
    return api.c.post(url, files={"file": (name, content, "image/jpeg")}, headers=api._h())


def test_scan_receipt_proposal(api, ids, receipt_ai):
    r = upload(api, "/api/receipts/scan", JPEG)
    assert r.status_code == 200, r.text
    body = r.json()
    p = body["proposal"]
    assert p["amount_cents"] == 15000
    assert p["description"] == "Posto Ipiranga"
    assert p["category_id"] == ids["cats"]["Combustível"]
    assert p["occurred_on"] <= date.today().isoformat()
    # Confirma e vincula o comprovante ao lançamento
    fields = (
        "type",
        "amount_cents",
        "occurred_on",
        "description",
        "category_id",
        "account_id",
        "payment_method",
    )
    tx = api.post("/api/transactions", {**{k: p[k] for k in fields}, "source": "ocr"}).json()
    att = body["attachment"]["id"]
    assert api.patch(f"/api/attachments/{att}", {"transaction_id": tx["id"]}).status_code == 200
    f = api.get(f"/api/attachments/{att}/file")
    assert f.status_code == 200 and f.content == JPEG


def test_scan_without_ai_keeps_file_and_explains(api):
    r = upload(api, "/api/receipts/scan", JPEG)
    assert r.status_code == 200
    assert r.json()["proposal"] is None
    assert "IA" in r.json()["error"]


def test_upload_rejects_fake_image(api):
    r = upload(api, "/api/receipts/scan", b"<script>alert(1)</script>", "x.jpg")
    assert r.status_code == 400


def test_export_csv_escapes_formulas(api):
    acc = api.post("/api/accounts", {"name": "Banco", "kind": "checking"}).json()
    api.post(
        "/api/transactions",
        {
            "type": "expense",
            "account_id": acc["id"],
            "amount_cents": 123456,
            "occurred_on": "2026-01-15",
            "description": '=HYPERLINK("x")',
        },
    )
    r = api.get("/api/export/transactions.csv")
    assert r.status_code == 200
    text = r.content.decode("utf-8-sig")
    assert "'=HYPERLINK" in text
    assert ";=HYPERLINK" not in text and ';"=HYPERLINK' not in text
    assert "1234,56" in text


def test_backup_export_and_idempotent_restore(api):
    acc = api.post("/api/accounts", {"name": "Banco", "kind": "checking"}).json()
    api.post(
        "/api/transactions",
        {
            "type": "expense",
            "account_id": acc["id"],
            "amount_cents": 500,
            "occurred_on": "2026-01-15",
            "description": "café",
        },
    )
    backup = api.get("/api/export/backup.json").json()
    assert backup["app"] == "JULIUS" and len(backup["transactions"]) == 1
    assert "password_hash" not in json.dumps(backup)
    r = api.c.post(
        "/api/import/backup",
        files={"file": ("b.json", json.dumps(backup), "application/json")},
        headers=api._h(),
    )
    assert r.status_code == 200
    assert all(v == 0 for v in r.json()["inserted"].values())  # nada duplicado


def test_backup_restore_rejects_garbage(api):
    r = api.c.post(
        "/api/import/backup",
        files={"file": ("b.json", b'{"app": "outro"}', "application/json")},
        headers=api._h(),
    )
    assert r.status_code == 400


def test_migrations_upgrade_downgrade_roundtrip():
    tmp = Path(tempfile.mkdtemp()) / "roundtrip.db"
    url = f"sqlite:///{tmp.as_posix()}"
    cfg = alembic_config(url)
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    assert "attachments" in inspect(engine).get_table_names()
    command.downgrade(cfg, "0001")
    assert "attachments" not in inspect(engine).get_table_names()
    assert "transactions" in inspect(engine).get_table_names()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    assert "attachments" in inspect(engine).get_table_names()
    engine.dispose()
