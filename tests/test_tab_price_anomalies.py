from copy import deepcopy
from io import BytesIO
from pathlib import Path
import openpyxl
import streamlit as st
import supabase
from streamlit.testing.v1 import AppTest
from tab_price_anomalies import category,price_checks,grouped_actions
from tab_management import management_report
from jj_intervention_status import build_status
from jj_report import excel_report
from tests.test_tab_management_ui import Backend

ROOT=Path(__file__).resolve().parents[1]

def model(backend):
 d=backend.data
 return management_report(d['jj_recon_records'],d['jj_recon_links'],d['clienti'],d['offerte_header'],d['offerte_clienti'],d['offerte_prezzi'],build_status)

def test_anomalies_are_exactly_the_management_checks_without_persisted_copies():
 backend=Backend();backend.data['offerte_prezzi']=[]
 original=backend.data['jj_recon_records'][2];other=deepcopy(original)
 other['id']=4;other['source_key']='other';other['payload']['encounter']='0008';backend.data['jj_recon_records'].append(other)
 report=model(backend);rows=price_checks(report)
 assert len(rows)==sum(r['Valore atteso'] is None for r in report['Prodotti TAB'])==2
 assert all(r['Categoria']=='Offerta / prezzo da verificare' for r in rows)
 groups=grouped_actions(rows)
 assert len(groups)==1 and groups[0]['Righe interessate']==2 and groups[0]['Pezzi interessati']==4
 content=excel_report({'Anomalie TAB':rows,'Azioni raggruppate':groups})
 wb=openpyxl.load_workbook(BytesIO(content));assert wb['Anomalie TAB'].max_row==3
 assert 'ID intervento TAB' not in list(wb['Anomalie TAB'].values)[0]
 before=deepcopy(backend.data['jj_recon_records'])
 backend.data['offerte_prezzi']=[{'offerta_id':1,'codice':'413.016S','prezzo':'10'}]
 assert price_checks(model(backend))==[]
 assert backend.data['jj_recon_records']==before and backend.writes==[]

def test_categories_distinguish_missing_structure_date_ambiguity_and_invoice():
 base={'Esito':'VALORIZZAZIONE DA VERIFICARE','Data intervento':'2026-01-01'}
 assert category({**base,'Motivo / azione':'Struttura non univoca in anagrafica'})=='Struttura da verificare'
 assert category({**base,'Data intervento':'','Motivo / azione':'Prezzo offerta mancante'})=='Data intervento da verificare'
 assert category({**base,'Motivo / azione':'Più offerte valide con prezzi diversi'})=='Offerte o REF ambigui'
 assert category({**base,'Esito':'FATTURA DIVERSA DALL’OFFERTA'})=='Differenza fattura / offerta'
 assert category({**base,'Esito':'PREZZO FATTURA MANCANTE'})=='Prezzo fattura mancante'

def test_grouped_invoice_actions_keep_distinct_presidi_with_same_erp_name():
 products=[];issues=[]
 for doc,cac,clinic in [('d1','100','Sapri'),('d2','200','Nocera')]:
  products.append({'Divisione':'TRAUMA','Documento TAB':doc,'REF':'R1','Lotto':'L1','Struttura':clinic,'CAC':cac,'Codice struttura':'9010000'})
  issues.append({'Divisione':'TRAUMA','Documento TAB':doc,'REF':'R1','Lotto':'L1','Struttura':'ASL SALERNO','Quantità':1,'Esito':'FATTURA DIVERSA DALL’OFFERTA'})
 rows=price_checks({'Prodotti TAB':products,'Prezzi da verificare':issues})
 assert {r['Struttura'] for r in rows}=={'Sapri','Nocera'}
 assert len(grouped_actions(rows))==2

def page(monkeypatch,backend):
 st.cache_resource.clear();st.cache_data.clear()
 monkeypatch.setattr(supabase,'create_client',lambda *a,**kw:backend)
 at=AppTest.from_file(str(ROOT/'pages/14_Anomalie_Prezzi.py'),default_timeout=30)
 at.secrets['SUPABASE_URL']='http://127.0.0.1:1';at.secrets['SUPABASE_SERVICE_KEY']='fake'
 at.session_state['user']='test';at.session_state['ruolo']='Admin';at.session_state['permessi']=['DIREZIONE']
 return at

def test_anomalies_page_shows_tab_without_legacy_rows_and_refreshes_offer_changes(monkeypatch):
 backend=Backend();backend.data['offerte_prezzi']=[]
 at=page(monkeypatch,backend).run()
 assert not at.exception
 assert next(m.value for m in at.metric if m.label=='Righe TAB senza prezzo')=='1'
 assert any('Prezzi TAB' in x.value for x in at.subheader)
 next(x for x in at.toggle if x.label=='Mostra dettaglio ed esportazione anomalie').set_value(True).run()
 assert any(x.proto.label=='Scarica Excel anomalie TAB' for x in at.get('download_button'))
 assert not any(x.value=='Nessuna anomalia prezzo da verificare.' for x in at.success)
 assert backend.writes==[]
 backend.data['offerte_prezzi']=[{'offerta_id':1,'codice':'413.016S','prezzo':'10'}]
 next(b for b in at.button if b.label=='Aggiorna anomalie TAB').click().run()
 assert not at.exception
 assert next(m.value for m in at.metric if m.label=='Segnalazioni TAB')=='0'
 assert any('Nessuna anomalia prezzo TAB' in x.value for x in at.success)
 assert backend.writes==[]
 next(r for r in at.radio if r.label=='Linea anomalie TAB').set_value('PROTESICA').run()
 assert not at.exception and any('Nessun TAB acquisito' in x.value for x in at.info)
 st.cache_resource.clear();st.cache_data.clear()

def test_tab_load_failure_does_not_claim_tab_has_no_anomalies(monkeypatch):
 backend=Backend();original=backend.execute
 def execute():
  if backend.name=='jj_recon_records':raise RuntimeError('private connection details')
  return original()
 backend.execute=execute
 at=page(monkeypatch,backend).run()
 assert not at.exception and any('Anomalie TAB non disponibili' in x.value for x in at.error)
 assert not any('Nessuna anomalia prezzo TAB' in x.value for x in at.success)
 assert not any('private connection details' in x.value for x in at.error)
 assert any('negli scarichi storici' in x.value for x in at.success)
 st.cache_resource.clear();st.cache_data.clear()

def test_management_anomalies_menu_opens_the_same_consolidated_page(monkeypatch):
 backend=Backend();st.cache_resource.clear();st.cache_data.clear()
 monkeypatch.setattr(supabase,'create_client',lambda *a,**kw:backend)
 at=AppTest.from_file(str(ROOT/'app.py'),default_timeout=30)
 at.secrets['SUPABASE_URL']='http://127.0.0.1:1';at.secrets['SUPABASE_SERVICE_KEY']='fake'
 at.session_state['user']='test';at.session_state['ruolo']='Admin';at.session_state['permessi']=['DIREZIONE']
 at.run();at.switch_page('core_app.py').run()
 next(r for r in at.radio if r.label=='Menu').set_value('Anomalie').run()
 assert not at.exception
 assert any('Anomalie Prezzi e Giacenze' in x.value for x in at.title)
 assert any('Prezzi TAB' in x.value for x in at.subheader)
 assert backend.writes==[]
 st.cache_resource.clear();st.cache_data.clear()
