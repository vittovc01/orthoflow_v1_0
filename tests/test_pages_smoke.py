"""Render real pages with an empty in-memory backend; never contact production."""
from types import SimpleNamespace
from pathlib import Path

import pytest
import streamlit as st
import supabase
from streamlit.testing.v1 import AppTest


class ReadOnlyBackend:
    def __init__(self):
        self.reads = []

    def table(self, name):
        self.reads.append(name)
        return self

    def execute(self):
        return SimpleNamespace(data=[], count=0)

    def __getattr__(self, name):
        if name in {"insert", "update", "delete", "upsert", "rpc"}:
            raise AssertionError(f"Unexpected write during page render: {name}")
        return lambda *args, **kwargs: self


@pytest.fixture
def backend(monkeypatch):
    st.cache_resource.clear()
    st.cache_data.clear()
    fake = ReadOnlyBackend()
    monkeypatch.setattr(supabase, "create_client", lambda *a, **kw: fake)
    yield fake
    st.cache_resource.clear()
    st.cache_data.clear()


def app():
    at = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30)
    at.secrets["SUPABASE_URL"] = "http://127.0.0.1:1"
    at.secrets["SUPABASE_SERVICE_KEY"] = "ci-dummy-key"
    return at


def test_login_renders_without_backend_access(backend):
    at = app().run()
    assert not at.exception
    assert any("Accedi" in b.label for b in at.button)
    assert backend.reads == []


@pytest.mark.parametrize("page", [
    "pages/00_Control_Tower.py",
    "pages/05_Scarico_Sala_AI.py",
    "pages/04_DDT_Carico_v2.py",
    "pages/06_Gestione_Interventi.py",
    "pages/09_Corrieri.py",
    "pages/14_Anomalie_Prezzi.py",
    "core_app.py",
])
def test_admin_page_renders_without_exception(page, backend):
    at = app()
    at.session_state["user"] = "ci-user"
    at.session_state["ruolo"] = "Admin"
    at.session_state["permessi"] = ["DIREZIONE"]
    at.run()
    at.switch_page(page).run()
    assert not at.exception
    assert not any("Accesso non autorizzato" in e.value for e in at.error)
    assert backend.reads, "Page stopped before loading its backend"


def test_scarico_uploaded_pdf_is_displayed_without_ocr_or_writes(backend, monkeypatch):
    from io import BytesIO
    from reportlab.pdfgen import canvas
    buf = BytesIO()
    pdf = canvas.Canvas(buf)
    pdf.drawString(40, 700, "Scarico dimostrativo - pagina 1")
    pdf.showPage()
    pdf.drawString(40, 700, "Scarico dimostrativo - pagina 2")
    pdf.save()
    payload = buf.getvalue()
    shown = []
    original = st.pdf
    def record_pdf(data, **kwargs):
        shown.append(data)
        return original(data, **kwargs)
    monkeypatch.setattr(st, "pdf", record_pdf)
    at = app()
    at.session_state["user"] = "ci-user"
    at.session_state["ruolo"] = "Admin"
    at.session_state["permessi"] = ["DIREZIONE"]
    at.run()
    at.session_state["scarico_pending_files"] = {"demo": {
        "name": "scarico-demo.pdf", "type": "application/pdf", "data": payload}}
    at.switch_page("pages/05_Scarico_Sala_AI.py").run()
    assert not at.exception
    assert shown == [payload], "Uploaded PDFs must not be silently omitted from preview"
    assert any(e.label == "Anteprima documenti (foto e PDF)" for e in at.expander)
