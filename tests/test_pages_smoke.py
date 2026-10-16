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
    next(b for b in at.button if b.label=='📤 Crea intervento e scarica materiali').click()
    at.run()
    assert not at.exception
    assert any('Conferma di aver verificato i materiali' in e.value for e in at.error)
    assert next(n for n in at.number_input if n.label.startswith('Numero di etichette')).value==1
    assert len([c for c in at.checkbox if c.label.startswith('Ho ')])==1


def test_single_confirmation_accepts_missing_gtin_and_advisory_count(backend,monkeypatch):
    calls=[]
    def rpc(name,args):
        calls.append((name,args))
        return SimpleNamespace(execute=lambda:SimpleNamespace(data={'intervento_id':123,'righe':1,'totale':0}))
    monkeypatch.setitem(backend.__dict__,'rpc',rpc)
    at=app()
    at.session_state['user']='ci-user';at.session_state['ruolo']='Admin';at.session_state['permessi']=['DIREZIONE']
    at.run()
    from label_pipeline import PIPELINE_VERSION
    at.session_state['scarico_source']='AI'
    at.session_state['scarico_ai_meta']={'pipeline_version':PIPELINE_VERSION}
    at.session_state['scarico_ai_rows']=[{'label_id':'one','codice':'TEST-A','lotto':'LOT-A',
        'scadenza':'2035-01-01','quantita':2,'gtin':float('nan'),'verificata':False}]
    at.switch_page('pages/05_Scarico_Sala_AI.py').run()
    assert not at.exception
    assert not any('GTIN' in t.label for t in at.text_input)
    assert len([c for c in at.checkbox if c.label.startswith('Ho ')])==1
    next(n for n in at.number_input if n.label.startswith('Numero di etichette')).set_value(3)
    next(c for c in at.checkbox if c.label.startswith('Ho controllato REF')).check()
    next(b for b in at.button if b.label=='📤 Crea intervento e scarica materiali').click()
    at.run()
    assert not at.exception
    name,args=next((name,args) for name,args in calls if name=='crea_intervento_scarico_ai_verificato')
    assert args['p_rows'][0]['quantita']==2
    assert args['p_header']['reported_label_count']==3 and args['p_header']['count_difference']==2
    assert args['p_header']['label_manifest'][0]['dati_confermati']['gtin'] is None
    assert not any('nan' in e.value for e in at.error)


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
    next(b for b in at.button if b.label=='Applica materiale alla lista').click()
    at.run()
    assert not at.exception
    assert at.session_state['scarico_ai_rows'][0]['codice']=='3095-040'
    assert at.session_state['scarico_ai_rows'][0]['label_id']=='original'
    next(s for s in at.selectbox if s.label=='Materiale da correggere').set_value(-1)
    at.run()
    for label,value in [('REF / codice','1506-70-005'),('Lotto stampato','LOT2'),('Scadenza stampata (AAAA-MM-GG)','2036-01-01')]:
        next(t for t in at.text_input if t.label==label).set_value(value)
    next(b for b in at.button if b.label=='Applica materiale alla lista').click()
    at.run()
    assert not at.exception
    rows=at.session_state['scarico_ai_rows']
    assert len(rows)==2
    assert rows[1]['manual_entry'] and rows[1]['crop_data_url'] is None
    assert rows[1]['gtin'] is None and rows[1]['quantita']==1
    assert any(l['field']=='codice' and l['method']=='manuale' and l['user']=='ci-user' for l in at.session_state['scarico_correction_log'])
    assert next(n for n in at.number_input if n.label.startswith('Numero di etichette')).value==2
    next(s for s in at.selectbox if s.label=='Materiale da correggere').set_value(0)
    at.run()
    next(b for b in at.button if b.label=='Elimina questa riga').click()
    at.run()
    assert not at.exception
    assert len(at.session_state['scarico_ai_rows'])==1
    assert next(n for n in at.number_input if n.label.startswith('Numero di etichette')).value==1
    assert any(l['operation']=='delete' for l in at.session_state['scarico_correction_log'])
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


def test_table_edits_additions_and_deletions_update_count_and_audit(backend):
    at=app()
    at.session_state['user']='agent';at.session_state['ruolo']='Admin';at.session_state['permessi']=['DIREZIONE']
    at.run()
    from label_pipeline import PIPELINE_VERSION
    at.session_state['scarico_source']='AI'
    at.session_state['scarico_ai_meta']={'pipeline_version':PIPELINE_VERSION}
    at.session_state['scarico_ai_rows']=[{'label_id':'one','codice':'TEST-A','lotto':'LOT-A',
        'scadenza':'2035-01-01','quantita':1,'gtin':None}]
    at.switch_page('pages/05_Scarico_Sala_AI.py').run()
    def editor_key():
        return f"scarico_ai_editor__{at.session_state['scarico_editor_revision'] if 'scarico_editor_revision' in at.session_state else 0}"
    key=editor_key()
    at.session_state[key]={'edited_rows':{0:{'codice':'TEST-B','quantita':2}},'added_rows':[],'deleted_rows':[]}
    at.run()
    assert not at.exception
    assert at.session_state['scarico_ai_rows'][0]['codice']=='TEST-B'
    assert at.session_state['scarico_ai_rows'][0]['quantita']==2
    at.session_state[editor_key()]={'edited_rows':{},'added_rows':[{'codice':'TEST-C','lotto':'LOT-C','scadenza':'2036-01-01','quantita':1}],'deleted_rows':[]}
    at.run()
    assert not at.exception
    assert len(at.session_state['scarico_ai_rows'])==2
    assert next(n for n in at.number_input if n.label.startswith('Numero di etichette')).value==2
    at.session_state[editor_key()]={'edited_rows':{},'added_rows':[],'deleted_rows':[0]}
    at.run()
    assert not at.exception
    assert len(at.session_state['scarico_ai_rows'])==1
    assert at.session_state['scarico_ai_rows'][0]['codice']=='TEST-C'
    assert next(n for n in at.number_input if n.label.startswith('Numero di etichette')).value==1
    operations={entry['operation'] for entry in at.session_state['scarico_correction_log']}
    assert operations=={'add','update','delete'}


def test_invalid_row_is_red_and_blocks_with_ref_and_lot(backend):
    at=app();at.session_state['user']='agent';at.session_state['ruolo']='Admin';at.session_state['permessi']=['DIREZIONE']
    at.run()
    from label_pipeline import PIPELINE_VERSION
    at.session_state['scarico_source']='AI'
    at.session_state['scarico_ai_meta']={'pipeline_version':PIPELINE_VERSION}
    at.session_state['scarico_ai_rows']=[
        {'label_id':'good','codice':'TEST-GOOD','lotto':'LOT-GOOD','scadenza':'2035-01-01','quantita':1},
        {'label_id':'bad','codice':'TEST-BAD','lotto':'LOT-BAD','scadenza':float('nan'),'quantita':1}]
    at.switch_page('pages/05_Scarico_Sala_AI.py').run()
    table=next(d for d in at.dataframe if 'esito' in d.value.columns)
    assert table.value['esito'][0]=='' and table.value['esito'][1].startswith('🔴')
    next(c for c in at.checkbox if c.label.startswith('Ho controllato REF')).check()
    next(b for b in at.button if b.label=='📤 Crea intervento e scarica materiali').click();at.run()
    assert not at.exception
    errors=[e.value for e in at.error]
    assert errors and all('TEST-BAD, lotto LOT-BAD: scadenza mancante' in e for e in errors)
    assert not any('nan' in e for e in errors)


def test_timeout_retry_reuses_discharge_request_uuid(backend,monkeypatch):
    calls=[]
    def rpc(name,args):
        if name!='crea_intervento_scarico_ai_verificato':
            return SimpleNamespace(execute=lambda:SimpleNamespace(data=[]))
        calls.append(args)
        def execute():
            if len(calls)==1:raise TimeoutError('response lost')
            return SimpleNamespace(data={'intervento_id':123,'righe':1,'totale':0,'replayed':True})
        return SimpleNamespace(execute=execute)
    monkeypatch.setitem(backend.__dict__,'rpc',rpc)
    at=app();at.session_state['user']='agent';at.session_state['ruolo']='Admin';at.session_state['permessi']=['DIREZIONE'];at.run()
    from label_pipeline import PIPELINE_VERSION
    at.session_state['scarico_source']='AI';at.session_state['scarico_ai_meta']={'pipeline_version':PIPELINE_VERSION}
    at.session_state['scarico_ai_rows']=[{'label_id':'one','codice':'TEST-A','lotto':'TEST-LOT','scadenza':'2035-01-01','quantita':1}]
    at.switch_page('pages/05_Scarico_Sala_AI.py').run()
    next(c for c in at.checkbox if c.label.startswith('Ho controllato REF')).check()
    next(b for b in at.button if b.label=='📤 Crea intervento e scarica materiali').click();at.run()
    assert not at.exception and len(calls)==1
    request_id=at.session_state['scarico_discharge_request_id']
    assert any('Esito scarico da verificare' in e.value for e in at.error)
    next(b for b in at.button if b.label=='📤 Crea intervento e scarica materiali').click();at.run()
    assert not at.exception and len(calls)==2
    assert calls[0]==calls[1]
    assert calls[1]['p_header']['request_id']==request_id
