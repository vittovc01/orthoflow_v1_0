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


def test_physical_label_review_blocks_unverified_count_without_writes(backend):
    from label_pipeline import image_url
    from PIL import Image
    at = app()
    at.session_state['user'] = 'ci-user'
    at.session_state['ruolo'] = 'Admin'
    at.session_state['permessi'] = ['DIREZIONE']
    at.run()
    at.session_state['scarico_source'] = 'AI'
    from label_pipeline import PIPELINE_VERSION
    at.session_state['scarico_ai_meta']={'pipeline_version':PIPELINE_VERSION}
    at.session_state['scarico_editor_revision'] = 1
    at.session_state['scarico_ai_rows'] = [{
        'label_id': 'document:p1:l1', 'codice': '413.040S', 'lotto': 'LOT',
        'scadenza': '2035-04-01', 'quantita': 1, 'produttore': 'Synthes',
        'confidence': .99, 'warning': '', 'verificata': False,
        'page': 1, 'bbox': [100,100,300,200], 'rotation': 180,
        'crop_data_url': image_url(Image.new('RGB',(100,40),'white')),
    }]
    at.switch_page('pages/05_Scarico_Sala_AI.py').run()
    assert not at.exception
    assert any(m.label=='Etichette individuate' and m.value=='1' for m in at.metric)
    next(c for c in at.checkbox if c.label.startswith('Ho verificato codice')).check()
    next(b for b in at.button if b.label=='📤 Crea intervento e scarica materiali').click()
    at.run()
    assert not at.exception
    assert any('Conteggio fisico non verificato' in e.value for e in at.error)
    assert any('verifica singola etichetta richiesta' in e.value for e in at.error)


def test_reviewed_labels_cannot_save_unverified_procedure_header(backend):
    at = app()
    at.session_state['user'] = 'ci-user'
    at.session_state['ruolo'] = 'Admin'
    at.session_state['permessi'] = ['DIREZIONE']
    at.run()
    at.session_state['scarico_source'] = 'AI'
    from label_pipeline import PIPELINE_VERSION
    at.session_state['scarico_ai_meta']={'pipeline_version':PIPELINE_VERSION}
    at.session_state['scarico_editor_revision'] = 1
    at.session_state['scarico_ai_rows'] = [{
        'label_id': 'document:p1:l1', 'codice': '413.040S', 'lotto': 'LOT',
        'scadenza': '2035-04-01', 'quantita': 1, 'produttore': 'Synthes',
        'confidence': .99, 'warning': '', 'verificata': True,
        'page': 1, 'bbox': [100,100,300,200], 'rotation': 0,
    }]
    at.switch_page('pages/05_Scarico_Sala_AI.py').run()
    next(n for n in at.number_input if n.label.startswith('Numero di etichette')).set_value(1)
    next(c for c in at.checkbox if c.label.startswith('Ho confrontato tutti')).check()
    next(c for c in at.checkbox if c.label.startswith('Ho verificato codice')).check()
    next(b for b in at.button if b.label=='📤 Crea intervento e scarica materiali').click()
    at.run()
    assert not at.exception
    assert any('verifica struttura, data e dati intervento' in e.value for e in at.error)


def test_manual_material_can_correct_or_add_missing_physical_label(backend, tmp_path):
    from PIL import Image
    from label_pipeline import review_errors
    document=tmp_path/'labels.jpg'
    Image.new('RGB',(300,200),'white').save(document)
    at=app()
    at.session_state['user']='ci-user'
    at.session_state['ruolo']='Admin'
    at.session_state['permessi']=['DIREZIONE']
    at.run()
    at.session_state['scarico_source']='AI'
    from label_pipeline import PIPELINE_VERSION
    at.session_state['scarico_ai_meta']={'pipeline_version':PIPELINE_VERSION}
    at.session_state['scarico_ai_rows']=[{'label_id':'original', 'codice':'3092-040',
        'lotto':'LOT', 'scadenza':'2030-01-01', 'quantita':1, 'verificata':False}]
    at.session_state['scarico_documents']=[{'name':'labels.jpg','path':str(document)}]
    at.switch_page('pages/05_Scarico_Sala_AI.py').run()
    next(t for t in at.text_input if t.label=='REF / codice').set_value('3095-040')
    next(c for c in at.checkbox if c.label.startswith('Ho confrontato questi')).check()
    next(b for b in at.button if b.label=='Applica materiale alla lista').click()
    at.run()
    assert not at.exception
    assert at.session_state['scarico_ai_rows'][0]['codice']=='3095-040'
    assert at.session_state['scarico_ai_rows'][0]['label_id']=='original'
    next(s for s in at.selectbox if s.label=='Materiale da correggere').set_value(-1)
    at.run()
    for label,value in [('REF / codice','1506-70-005'),('Lotto stampato','LOT2'),('Scadenza stampata (AAAA-MM-GG)','2036-01-01')]:
        next(t for t in at.text_input if t.label==label).set_value(value)
    next(c for c in at.checkbox if c.label.startswith('Ho confrontato questi')).check()
    next(b for b in at.button if b.label=='Applica materiale alla lista').click()
    at.run()
    assert not at.exception
    rows=at.session_state['scarico_ai_rows']
    assert len(rows)==2
    assert rows[1]['source_document'] and rows[1]['crop_data_url'] is None
    assert rows[1]['page']==1 and rows[1]['quantita']==1
    assert not review_errors(rows,[r['label_id'] for r in rows],2,True)


def test_old_preprivacy_session_cannot_render_stale_header_crops(backend):
    at=app()
    at.session_state['user']='ci-user'
    at.session_state['ruolo']='Admin'
    at.session_state['permessi']=['DIREZIONE']
    at.run()
    at.session_state['scarico_source']='AI'
    at.session_state['scarico_ai_rows']=[{'label_id':'old-header','codice':''}]
    at.session_state['scarico_ai_meta']={'pipeline_version':'old-unredacted-version'}
    at.switch_page('pages/05_Scarico_Sala_AI.py').run()
    assert not at.exception
    assert any('filtro privacy' in w.value for w in at.warning)
    assert not at.expander
