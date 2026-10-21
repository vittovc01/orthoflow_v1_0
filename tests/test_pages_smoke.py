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
        return SimpleNamespace(data=[
            {'codice_cliente':'A','descrizione':'Struttura A'},
            {'codice_cliente':'B','descrizione':'Struttura B'},
        ] if self.reads and self.reads[-1]=='clienti' else [], count=0)

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
    at.secrets["OCR_REVIEW_ARCHIVE_ENABLED"] = "false"
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
    next(s for s in at.selectbox if s.label=='Struttura / cliente').select_index(0)
    next(s for s in at.selectbox if s.label=='Linea').select('TRAUMA')
    at.run()
    assert not at.exception
    assert any(m.label=='Etichette individuate' and m.value=='1' for m in at.metric)
    next(b for b in at.button if b.label=='📤 Crea intervento e scarica materiali').click()
    at.run()
    assert not at.exception
    assert any('Conferma di aver verificato i materiali' in e.value for e in at.error)
    assert next(n for n in at.number_input if n.label.startswith('Numero di etichette')).value==1
    assert len([c for c in at.checkbox if c.label.startswith('Ho ')])==1


def test_material_list_exports_and_catalogue_snapshot_without_technical_noise(backend, monkeypatch):
    import csv
    from io import StringIO
    import review_exports
    downloads = {}
    original_csv, original_xlsx = review_exports.review_csv, review_exports.review_xlsx
    def capture_csv(rows):
        downloads['Scarica lista CSV'] = original_csv(rows)
        return downloads['Scarica lista CSV']
    def capture_xlsx(rows):
        downloads['Scarica lista Excel'] = original_xlsx(rows)
        return downloads['Scarica lista Excel']
    monkeypatch.setattr(review_exports, 'review_csv', capture_csv)
    monkeypatch.setattr(review_exports, 'review_xlsx', capture_xlsx)
    at = app()
    at.session_state['user']='ci-user';at.session_state['ruolo']='Admin';at.session_state['permessi']=['DIREZIONE']
    at.run()
    from label_pipeline import PIPELINE_VERSION
    at.session_state['scarico_source']='AI'
    at.session_state['scarico_ai_meta']={'pipeline_version':PIPELINE_VERSION}
    at.session_state['scarico_ai_rows']=[dict(label_id='one',codice='04.200.030S',lotto='00123',
        scadenza='2035-01-01',descrizione='Vite',quantita=1,gtin=None)]
    at.switch_page('pages/05_Scarico_Sala_AI.py').run()
    assert not at.exception
    assert not any('GTIN' in c.value or 'catalogo' in c.value for c in at.caption)
    assert not any(e.label.startswith(('Da confermare','⚠️ Da verificare')) for e in at.expander)
    assert len(at.dataframe) == 1, 'show only the editable material list by default'
    assert list(at.dataframe[0].value.columns)[2:7] == ['codice','lotto','scadenza','descrizione','quantita']
    assert {'Scarica lista Excel','Scarica lista CSV'} <= downloads.keys()
    reads = backend.reads.count('articoli_gtin')
    editor_key = 'scarico_ai_editor__0'
    at.session_state[editor_key]={'edited_rows':{0:{'lotto':'00999','quantita':2}},'added_rows':[],'deleted_rows':[]}
    at.run()
    assert not at.exception
    records = list(csv.DictReader(StringIO(downloads['Scarica lista CSV'].decode('utf-8-sig')),delimiter=';'))
    assert records[0]['Lotto']=='00999' and records[0]['Quantità']=='2'
    assert backend.reads.count('articoli_gtin') == reads == 0  # no detected GTIN: no catalogue download
    assert any(l['field']=='lotto' for l in at.session_state['scarico_correction_log'])
    assert len([c for c in at.checkbox if c.label.startswith('Ho controllato')]) == 1


@pytest.mark.parametrize('legacy_wrapper',[False,True])
def test_single_confirmation_accepts_missing_gtin_and_advisory_count(backend,monkeypatch,legacy_wrapper):
    calls=[]
    def rpc(name,args):
        calls.append((name,args))
        return SimpleNamespace(execute=lambda:SimpleNamespace(data={'intervento_id':123,'righe':1,'totale':0}))
    monkeypatch.setitem(backend.__dict__,'rpc',rpc)
    at=app()
    at.session_state['user']='ci-user';at.session_state['ruolo']='Admin';at.session_state['permessi']=['DIREZIONE']
    at.run()
    if legacy_wrapper:
        native_submit=st._main.form_submit_button
        def obsolete_submit(label,*args,**kwargs):
            clicked=native_submit(label,*args,**kwargs)
            if clicked and label=='📤 Crea intervento e scarica materiali':
                st.warning('Spunta la verifica di codici, lotti, scadenze e quantità prima di creare l’intervento.')
                return False
            return clicked
        monkeypatch.setattr(st,'form_submit_button',obsolete_submit)
    from label_pipeline import PIPELINE_VERSION
    at.session_state['scarico_source']='AI'
    at.session_state['scarico_ai_meta']={'pipeline_version':PIPELINE_VERSION}
    at.session_state['scarico_ai_rows']=[{'label_id':'one','codice':'TEST-A','lotto':'LOT-A',
        'scadenza':'2035-01-01','quantita':2,'gtin':float('nan'),'verificata':False}]
    at.switch_page('pages/05_Scarico_Sala_AI.py').run()
    next(s for s in at.selectbox if s.label=='Struttura / cliente').select_index(0)
    next(s for s in at.selectbox if s.label=='Linea').select('TRAUMA')
    at.run()
    assert not at.exception
    assert not any('GTIN' in t.label for t in at.text_input)
    assert len([c for c in at.checkbox if c.label.startswith('Ho ')])==1
    next(n for n in at.number_input if n.label.startswith('Numero di etichette')).set_value(3)
    next(c for c in at.checkbox if c.label.startswith('Ho controllato REF')).check()
    next(b for b in at.button if b.label=='📤 Crea intervento e scarica materiali').click()
    at.run()
    assert not at.exception
    name,args=next((name,args) for name,args in calls if name=='crea_intervento_scarico_ai_verificato_v2')
    assert args['p_rows'][0]['quantita']==2
    assert args['p_header']['reported_label_count']==3 and args['p_header']['count_difference']==2
    assert args['p_header']['label_manifest'][0]['dati_confermati']['gtin'] is None
    assert not any('nan' in e.value for e in at.error)
    assert not any('Spunta la verifica' in w.value for w in at.warning)


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
    assert any('lettura della foto intera' in w.value for w in at.warning)
    assert not at.expander
    at.run()
    assert not at.exception and not at.expander
    assert any(b.label=='Rianalizza i documenti con la versione aggiornata' for b in at.button)


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
    next(s for s in at.selectbox if s.label=='Struttura / cliente').select_index(0)
    next(s for s in at.selectbox if s.label=='Linea').select('TRAUMA')
    at.run()
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
        if name!='crea_intervento_scarico_ai_verificato_v2':
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
    next(s for s in at.selectbox if s.label=='Struttura / cliente').select_index(0)
    next(s for s in at.selectbox if s.label=='Linea').select('TRAUMA')
    at.run()
    next(c for c in at.checkbox if c.label.startswith('Ho controllato REF')).check()
    next(b for b in at.button if b.label=='📤 Crea intervento e scarica materiali').click();at.run()
    assert not at.exception and len(calls)==1
    request_id=at.session_state['scarico_discharge_request_id']
    assert any('Esito scarico da verificare' in e.value for e in at.error)
    next(b for b in at.button if b.label=='📤 Crea intervento e scarica materiali').click();at.run()
    assert not at.exception and len(calls)==2
    assert calls[0]==calls[1]
    assert calls[1]['p_header']['request_id']==request_id


def test_archive_enabled_saves_product_review_without_discharge(backend,monkeypatch):
    at=app();at.secrets['OCR_REVIEW_ARCHIVE_ENABLED']='true'
    at.session_state['user']='agent';at.session_state['ruolo']='Admin';at.session_state['permessi']=['DIREZIONE'];at.run()
    from label_pipeline import PIPELINE_VERSION
    original={'label_id':'one','codice':'TEST-A','lotto':'LOT-A','scadenza':'2035-01-01','quantita':1}
    at.session_state['scarico_source']='AI';at.session_state['scarico_ai_meta']={'pipeline_version':PIPELINE_VERSION}
    at.session_state['scarico_ai_rows']=[original]
    at.session_state['scarico_ai_original_rows']=[original]
    at.session_state['scarico_documents']=[{'path':'/must-not-be-read/private-patient.pdf'}]
    at.switch_page('pages/05_Scarico_Sala_AI.py').run()
    import ocr_repository
    calls=[]
    def save(self,**kwargs):
        calls.append(kwargs)
        return {'id':kwargs['request_id']}
    monkeypatch.setattr(ocr_repository.SupabaseReviewRepository,'save_product_review',save)
    next(c for c in at.checkbox if c.label.startswith('Ho controllato REF')).check()
    button=next(b for b in at.button if b.label.startswith('Conferma e archivia'))
    assert not button.disabled
    button.click();at.run()
    assert not at.exception and len(calls)==1
    assert 'documents' not in calls[0]
    assert any('Nessuno scarico' in s.value for s in at.success)


@pytest.mark.parametrize("legacy", [False, True])
def test_intervention_customer_selector_updates_code_and_name_together(backend, monkeypatch, legacy):
    saved = {
        "id": 42, "cliente": "Struttura storica" if legacy else "Clinica Alfa",
        "struttura": "Struttura storica" if legacy else "Clinica Alfa",
        "codice_cliente": "OLD" if legacy else "0001",
        "data_intervento": "2026-10-20", "linea": "TRAUMA", "magazzino": "MAG1",
    }
    # Duplicate descriptions are deliberately distinguished by customer code.
    customers = [{"codice_cliente": "0001", "descrizione": "Clinica Alfa"},
                 {"codice_cliente": "0002", "descrizione": "Clinica Alfa"},
                 {"codice_cliente": "0003", "descrizione_cliente": "Clinica Zeta"}]
    updates, pages = [], []
    class Query:
        def __init__(self, table):
            self.name, self.payload, self.bounds = table, None, None
        def update(self, payload):
            self.payload = payload
            return self
        def insert(self, payload):
            assert self.name == "audit_log"
            return self
        def range(self, lo, hi):
            self.bounds = (lo, hi)
            return self
        def execute(self):
            if self.payload is not None:
                assert self.name == "interventi"
                updates.append(self.payload)
                saved.update(self.payload)
                return SimpleNamespace(data=[])
            if self.name == "interventi":
                return SimpleNamespace(data=[dict(saved)])
            if self.name == "clienti":
                pages.append(self.bounds)
                # Simulate a server page cap smaller than requested.
                offset = self.bounds[0]
                return SimpleNamespace(data=customers[offset:offset+2])
            return SimpleNamespace(data=[])
        def __getattr__(self, name):
            assert name not in {"delete", "upsert", "rpc"}
            return lambda *a, **kw: self
    monkeypatch.setattr(backend, "table", lambda name: Query(name))
    monkeypatch.setitem(backend.__dict__, "rpc", lambda *a, **kw: SimpleNamespace(execute=lambda: SimpleNamespace(data=[])))
    at = app()
    at.session_state["user"]="ci-user";at.session_state["ruolo"]="Admin";at.session_state["permessi"]=["DIREZIONE"]
    at.run()
    at.switch_page("pages/06_Gestione_Interventi.py").run()
    assert not at.exception
    chooser = next(s for s in at.selectbox if s.label == "Cliente / struttura")
    assert len(chooser.options) == 4
    assert chooser.value == (None if legacy else "0001")
    assert (0,499) in pages and (2,501) in pages and (3,502) in pages
    assert not any(t.label in {"Codice cliente", "Cliente / struttura"} for t in at.text_input)
    chooser.set_value("0002")
    at.run()
    assert not at.exception and not updates
    assert any("Codice struttura associato: 0002" in c.value for c in at.caption)
    next(b for b in at.button if b.label == "💾 Salva dati intervento").click()
    at.run()
    assert not at.exception and len(updates) == 1
    assert updates[0]["codice_cliente"] == "0002"
    assert updates[0]["cliente"] == updates[0]["struttura"] == "Clinica Alfa"
    assert next(s for s in at.selectbox if s.label == "Cliente / struttura").value == "0002"


@pytest.mark.parametrize("new_price,preview_failure", [(12.5,False),(None,False),(12.5,True)])
def test_structure_price_preview_and_save_clear_old_editor(backend,monkeypatch,new_price,preview_failure):
    saved={"id":77,"codice_cliente":"A","cliente":"Alfa","struttura":"Alfa",
           "data_intervento":"2026-10-20","linea":"TRAUMA","magazzino":"MAG1"}
    material={"id":10,"intervento_id":77,"codice":"1504-00-126","lotto":"LOT",
              "quantita":2,"prezzo":90,"totale":180,"valore":180,
              "prezzo_source":"MANUALE","origine":"CONTO DEPOSITO","scadenza":"2035-01-01"}
    updates,requests=[],[]
    class Query:
        def __init__(self,name):self.name=name;self.payload=None;self.bounds=None;self.filters={}
        def eq(self,k,v):self.filters[k]=v;return self
        def update(self,payload):self.payload=payload;return self
        def range(self,lo,hi):self.bounds=(lo,hi);return self
        def insert(self,payload):
            assert self.name=="audit_log"
            return self
        def execute(self):
            if self.payload is not None:
                assert self.name=="interventi"
                updates.append(self.payload);saved.update(self.payload)
                material.update(prezzo=new_price,totale=None if new_price is None else 2*new_price,
                                valore=None if new_price is None else 2*new_price,
                                prezzo_source="RICALCOLO_SENZA_OFFERTA" if new_price is None else "OFFERTA")
                return SimpleNamespace(data=[])
            if self.name=="interventi":return SimpleNamespace(data=[dict(saved)])
            if self.name=="clienti":
                return SimpleNamespace(data=[] if self.bounds[0] else [
                    {"codice_cliente":"A","descrizione":"Alfa"},{"codice_cliente":"B","descrizione":"Beta"}])
            if self.name=="righe_intervento":
                return SimpleNamespace(data=[dict(material)] if not self.filters.get("origine") else [])
            return SimpleNamespace(data=[])
        def __getattr__(self,name):
            assert name not in {"delete","upsert"}
            return lambda *a,**kw:self
    def rpc(name,args):
        requests.append((name,args))
        def execute():
            if name!="anteprima_prezzi_cambio_struttura":return SimpleNamespace(data=[])
            if preview_failure:raise TimeoutError("temporary error")
            return SimpleNamespace(data=[{"riga_id":10,"codice":material["codice"],"lotto":"LOT",
                "prezzo_precedente":90,"prezzo_nuovo":new_price,
                "totale_nuovo":None if new_price is None else 2*new_price,"offerta_id":1,
                "esito":"PREZZO DA INSERIRE" if new_price is None else "OFFERTA"}])
        return SimpleNamespace(execute=execute)
    monkeypatch.setattr(backend,"table",lambda name:Query(name))
    monkeypatch.setitem(backend.__dict__,"rpc",rpc)
    at=app();at.session_state["user"]="ci-user";at.session_state["ruolo"]="Admin";at.session_state["permessi"]=["DIREZIONE"]
    at.run();at.switch_page("pages/06_Gestione_Interventi.py").run()
    assert not at.exception
    # An old unsaved material-price edit must not survive a customer switch.
    at.session_state["intervento_editor_full_77_A_TRAUMA"]={"edited_rows":{0:{"prezzo":999}},"added_rows":[],"deleted_rows":[]}
    next(s for s in at.selectbox if s.label=="Cliente / struttura").set_value("B")
    at.run()
    assert not at.exception and not updates
    request=next(args for name,args in requests if name=="anteprima_prezzi_cambio_struttura" and args["p_codice_cliente"]=="B")
    assert request["p_codice_cliente"]=="B" and request["p_linea"]=="TRAUMA" and request["p_data"]=="2026-10-20"
    if not preview_failure:
        assert any("vecchio prezzo verrà rimosso" in w.value for w in at.warning) == (new_price is None)
    next(b for b in at.button if b.label=="💾 Salva dati intervento").click();at.run()
    assert not at.exception
    if preview_failure:
        assert not updates
        assert any("nessuna modifica verrà salvata" in e.value for e in at.error)
    else:
        assert len(updates)==1 and saved["codice_cliente"]=="B"
        table=next(d.value for d in at.dataframe if "prezzo_source" not in d.value.columns and "prezzo" in d.value.columns)
        if new_price is None:
            import pandas as pd
            assert pd.isna(table.iloc[0]["prezzo"])
            assert any("totale è incompleto" in w.value for w in at.warning)
        else:
            assert table.iloc[0]["prezzo"]==new_price and table.iloc[0]["totale"]==25


def test_smart_track_flags_reach_final_discharge_after_multiple_toggles(backend,monkeypatch):
    calls=[]
    class Query:
        def __init__(self,name):self.name=name
        def execute(self):
            return SimpleNamespace(data=[{"codice_cliente":"9010013","descrizione":"Malzoni"}] if self.name=="clienti" else [])
        def __getattr__(self,name):
            assert name not in {"insert","update","delete","upsert"}
            return lambda *a,**kw:self
    def rpc(name,args):
        calls.append((name,args))
        return SimpleNamespace(execute=lambda:SimpleNamespace(data={"intervento_id":123,"righe":2,"totale":0}))
    monkeypatch.setattr(backend,"table",lambda name:Query(name))
    monkeypatch.setitem(backend.__dict__,"rpc",rpc)
    at=app();at.session_state["user"]="ci-user";at.session_state["ruolo"]="Admin";at.session_state["permessi"]=["DIREZIONE"]
    at.run()
    from label_pipeline import PIPELINE_VERSION
    at.session_state["scarico_source"]="AI";at.session_state["scarico_ai_meta"]={"pipeline_version":PIPELINE_VERSION}
    at.session_state["scarico_ai_rows"]=[dict(label_id=f"label-{i}",codice="TEST-A",lotto=f"LOT{i}",
        scadenza="2035-01-01",quantita=1,produttore="Synthes") for i in range(2)]
    at.switch_page("pages/05_Scarico_Sala_AI.py").run()
    next(s for s in at.selectbox if s.label=='Struttura / cliente').select_index(0)
    next(s for s in at.selectbox if s.label=='Linea').select('TRAUMA')
    at.run()
    assert not at.exception
    for values in [(True,False),(True,True),(False,True)]:
        at.session_state["scarico_ai_editor_9010013_0"]={"edited_rows":{
            i:{"conto_deposito_struttura":v} for i,v in enumerate(values)},"added_rows":[],"deleted_rows":[]}
        at.run()
        assert not at.exception and not calls
        assert [r["conto_deposito_struttura"] for r in at.session_state["scarico_ai_rows"]]==list(values)
        assert at.session_state["scarico_editor_revision"]==0 if "scarico_editor_revision" in at.session_state else True
    next(c for c in at.checkbox if c.label.startswith("Ho controllato REF")).check()
    next(b for b in at.button if b.label=="📤 Crea intervento e scarica materiali").click();at.run()
    assert not at.exception
    args=next(args for name,args in calls if name=="crea_intervento_scarico_ai_verificato_v2")
    assert [r["conto_deposito_struttura"] for r in args["p_rows"]]==[False,True]


def test_destination_starts_empty_and_both_fields_are_required(backend):
    from label_pipeline import PIPELINE_VERSION
    at=app()
    at.session_state['user']='ci-user';at.session_state['ruolo']='Admin';at.session_state['permessi']=['DIREZIONE']
    at.run()
    at.session_state['scarico_price_line']='TRAUMA'  # old live session before this update
    at.session_state['scarico_source']='AI'
    at.session_state['scarico_ai_meta']={'pipeline_version':PIPELINE_VERSION, 'clinic_name':'Struttura A'}
    at.session_state['scarico_ai_rows']=[dict(label_id='one',codice='TEST',lotto='LOT',scadenza='2035-01-01',quantita=1)]
    at.switch_page('pages/05_Scarico_Sala_AI.py').run()
    assert not at.exception
    structure=lambda: next(s for s in at.selectbox if s.label=='Struttura / cliente')
    line=lambda: next(s for s in at.selectbox if s.label=='Linea')
    submit=lambda: next(b for b in at.button if b.label=='📤 Crea intervento e scarica materiali')
    assert structure().value is None and line().value is None
    assert submit().disabled
    structure().select_index(0);at.run()
    assert line().value is None and submit().disabled
    line().select('PROTESICA');at.run()
    assert not submit().disabled
    at.session_state['scarico_reset_destination']=True
    at.run()
    assert not at.exception
    assert structure().value is None and line().value is None and submit().disabled
