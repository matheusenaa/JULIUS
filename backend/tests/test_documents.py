"""Documentos: leitura sem IA (PDF + boleto), validação de upload, revisão e confirmação."""

from datetime import date, timedelta

import pytest
from fpdf import FPDF

from app.ai import doc_parser
from app.ai.providers import set_provider_for_tests

TODAY = date.today()


def boleto_line(amount_cents: int, due: date) -> str:
    """Gera uma linha digitável FEBRABAN válida (dígitos verificadores calculados)."""
    factor = (due - date(2025, 2, 22)).days + 1000
    free = "1234567890123456789012345"
    f1 = "341" + "9" + free[:5]
    f2 = free[5:15]
    f3 = free[15:25]
    dv = doc_parser._mod10
    return (
        f"{f1[:5]}.{f1[5:]}{dv(f1)} {f2[:5]}.{f2[5:]}{dv(f2)} {f3[:5]}.{f3[5:]}{dv(f3)} 7 "
        f"{factor:04d}{amount_cents:010d}"
    )


def bill_pdf(text_lines: list[str]) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    for line in text_lines:
        pdf.cell(0, 8, line, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def upload(api, content: bytes, name: str, mime: str, url="/api/documents", **form):
    return api.c.post(url, files={"file": (name, content, mime)}, data=form, headers=api._h())


# ---------- Unidade ----------
def test_decode_boleto_exact_values():
    due = TODAY + timedelta(days=7)
    decoded = doc_parser.decode_boleto(boleto_line(9990, due), TODAY)
    assert decoded["valid"] is True
    assert decoded["amount_cents"] == 9990
    assert decoded["due_date"] == due
    assert decoded["institution"] == "Itaú"


def test_decode_boleto_detects_typo():
    line = boleto_line(9990, TODAY + timedelta(days=7))
    broken = line.replace("67890.", "67891.", 1)  # um dígito errado no 2º campo
    assert broken != line
    assert doc_parser.decode_boleto(broken, TODAY)["valid"] is False


def test_parse_text_labels():
    text = (
        "Vivo Internet\nBeneficiário: Telefônica Brasil S.A.\nVencimento: 10/11/2026\nValor a pagar: R$ 99,90"
    )
    ex = doc_parser.parse_text(text, date(2026, 10, 4))
    assert ex.amount_cents == 9990
    assert ex.due_date == date(2026, 11, 10)
    assert ex.category_name == "Internet"
    assert ex.recurring_hint is True


# ---------- API ----------
def test_pdf_bill_read_without_ai(api, ids):
    due = TODAY + timedelta(days=6)
    pdf = bill_pdf(
        [
            "Conta de Internet - Vivo",
            "Beneficiario: Telefonica Brasil SA",
            f"Vencimento: {due.strftime('%d/%m/%Y')}",
            "Valor do documento: R$ 99,90",
            boleto_line(9990, due),
        ]
    )
    r = upload(api, pdf, "conta.pdf", "application/pdf")
    assert r.status_code == 201, r.text
    body = r.json()
    doc, p = body["document"], body["proposal"]
    assert body["error"] is None
    assert doc["status"] == "review" and doc["kind"] == "bill" and doc["barcode_valid"] is True
    assert p["amount_cents"] == 9990
    assert p["occurred_on"] == due.isoformat() and p["status"] == "pending"  # conta a vencer = prevista
    assert p["category_id"] == ids["cats"]["Internet"]
    assert p["recurrence"] == {"frequency": "monthly", "day_of_month": due.day}
    assert "Linha digitável" in p["notes"]

    # Confirmar como recorrência mensal + lançamento do mês
    tx = {
        k: p[k]
        for k in ("type", "amount_cents", "occurred_on", "description", "category_id", "account_id", "status")
    }
    rec = {
        "type": "expense",
        "account_id": p["account_id"],
        "description": p["description"],
        "amount_cents": 9990,
        "category_id": p["category_id"],
        "start_date": (due + timedelta(days=31)).isoformat(),
        "day_of_month": due.day,
    }
    c = api.post(f"/api/documents/{doc['id']}/confirm", {"transaction": tx, "recurrence": rec})
    assert c.status_code == 200, c.text
    assert c.json()["document"]["status"] == "confirmed" and c.json()["transaction_id"]
    assert api.post(f"/api/documents/{doc['id']}/confirm", {"transaction": tx}).status_code == 409
    files = api.get(f"/api/documents/{doc['id']}/file")
    assert files.status_code == 200 and files.content == pdf
    assert "sandbox" in files.headers["content-security-policy"]


def test_photo_without_ai_is_kept_for_manual_review(api):
    jpeg = b"\xff\xd8\xff\xe0" + b"0" * 300
    r = upload(api, jpeg, "foto.jpg", "image/jpeg")
    assert r.status_code == 201
    assert r.json()["proposal"] is None and "IA" in r.json()["error"]
    docs = api.get("/api/documents").json()
    assert docs["total"] == 1 and docs["items"][0]["status"] == "review"


@pytest.mark.parametrize(
    ("content", "name", "message"),
    [
        (b"<html><script>alert(1)</script>", "x.pdf", "Formato"),
        (b"\xff\xd8\xff\xe0" + b"0" * 100, "foto.pdf", "extensão"),
        (b"%PDF-1.4\n1 0 obj", "cortado.pdf", "incompleto"),
        (b"", "vazio.pdf", "vazio"),
    ],
)
def test_upload_validation(api, content, name, message):
    r = upload(api, content, name, "application/pdf")
    assert r.status_code == 400 and message.lower() in r.json()["error"]["message"].lower()


def test_ai_reads_photo_and_cannot_override_valid_boleto(api, ids):
    due = TODAY + timedelta(days=3)
    line = boleto_line(15000, due)

    class FakeAI:
        name = "fake"

        def generate_json(self, system, prompt, image=None, mime=None):
            return {
                "document_type": "boleto",
                "title": "Conta de luz",
                "total": 999.99,
                "barcode": line,
                "due_date": "2030-01-01",
                "recurring": True,
                "legible": True,
            }

    set_provider_for_tests(FakeAI())
    try:
        r = upload(api, b"\xff\xd8\xff\xe0" + b"1" * 300, "luz.jpg", "image/jpeg")
    finally:
        set_provider_for_tests(None)
    p = r.json()["proposal"]
    assert p["amount_cents"] == 15000  # valor decodificado do boleto, não o "total" da IA
    assert p["occurred_on"] == due.isoformat()


def test_delete_document_removes_file(api):
    pdf = bill_pdf(["Recibo", "Valor: R$ 10,00"])
    doc = upload(api, pdf, "recibo.pdf", "application/pdf").json()["document"]
    assert api.delete(f"/api/documents/{doc['id']}").status_code == 204
    assert api.get(f"/api/documents/{doc['id']}/file").status_code == 404
    assert api.get("/api/documents").json()["total"] == 0


def test_local_storage_backend(api, monkeypatch, tmp_path):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "storage_backend", "local")
    monkeypatch.setattr(get_settings(), "storage_dir", str(tmp_path))
    pdf = bill_pdf(["Recibo", "Valor: R$ 12,00"])
    doc = upload(api, pdf, "r.pdf", "application/pdf").json()["document"]
    stored = list(tmp_path.rglob("*.bin"))
    assert len(stored) == 1 and stored[0].read_bytes() == pdf
    assert api.get(f"/api/documents/{doc['id']}/file").content == pdf
    api.delete(f"/api/documents/{doc['id']}")
    assert not list(tmp_path.rglob("*.bin"))
