from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import streamlit as st
import supabase
from streamlit.testing.v1 import AppTest
from tests.test_jj_intervention_status import sources
from tests.test_jj_report import link
from tests.test_tab_management import catalogs

ROOT=Path(__file__).resolve().parents[1]

class Backend:
 def __init__(self,with_tab=True):
  cats=catalogs();records=sources() if with_tab else []
  if records:records[2]['payload']['customer']='Sapri'
  self.data=dict(zip(('clienti','offerte_header','offerte_clienti','offerte_prezzi'),cats))
  self.data.update({'jj_recon_records':records,'jj_recon_links':[link(2)] if with_tab else [],
    'interventi':[{'id':900,'cliente':'Sapri','cartella_clinica':'0007','data_intervento':'2026-09-01','linea':'TRAUMA'}]})
  self.reads=[];self.writes=[]
 def table(self,name):self.name=name;return self
 def select(self,*a,**kw):return self
 def order(self,*a,**kw):return self
 def range(self,*a):return self
 def limit(self,*a):return self
 def eq(self,*a):return self
 def execute(self):self.reads.append(self.name);return SimpleNamespace(data=deepcopy(self.data.get(self.name,[])),count=0)
 def rpc(self,name,args):
  assert name in ('jj_import_records','jj_review_record');self.writes.append((name,args))
  def save():
   if name=='jj_review_record':
    next(r for r in self.data['jj_recon_records'] if r['id']==args['p_id'])['payload']=args['p_payload']
    for l in self.data['jj_recon_links']:
     if l['implant_id']==args['p_id']:l['revoked_at']='test'
    return SimpleNamespace(data=None)
   for n,r in enumerate(args['p_records']):self.data['jj_recon_records'].append({'id':n+1,'kind':'IMPIANTO','division':args['p_division'],**r})
   return SimpleNamespace(data={'nuovi':len(args['p_records'])})
  return SimpleNamespace(execute=save)
 def __getattr__(self,name):
  if name in ('insert','update','delete','upsert'):raise AssertionError('No direct mutation of stock or legacy interventions')
  return lambda *a,**kw:self

def app(monkeypatch,backend,page='pages/06_Gestione_Interventi.py'):
 st.cache_resource.clear();st.cache_data.clear()
 monkeypatch.setattr(supabase,'create_client',lambda *a,**kw:backend)
 at=AppTest.from_file(str(ROOT/page),default_timeout=30)
 at.secrets['SUPABASE_URL']='http://127.0.0.1:1';at.secrets['SUPABASE_SERVICE_KEY']='fake'
 at.session_state['user']={'id':'test'};at.session_state['ruolo']='Admin';at.session_state['permessi']=['DIREZIONE']
 return at

def test_tab_management_is_default_and_never_reads_or_adds_duplicate_legacy_intervention(monkeypatch):
 backend=Backend();at=app(monkeypatch,backend).run()
 assert not at.exception
 assert next(x for x in at.radio if x.label=='Fonte interventi').value=='Interventi TAB'
 assert [m.value for m in at.metric][:2]==['1','2']
 assert not {'interventi','righe_intervento','movimenti_magazzino','giacenze'}&set(backend.reads)
 assert not backend.writes
 assert any(x.proto.label=='Scarica Excel gestione TAB' for x in at.get('download_button'))
 backend.data['offerte_prezzi'][0]['prezzo']='9'
 next(b for b in at.button if b.label=='Aggiorna dati TAB').click().run()
 assert not at.exception and any(m.value=='€ 18.00' for m in at.metric)
 st.cache_resource.clear();st.cache_data.clear()

def test_tab_upload_uses_only_accounting_rpc_and_becomes_visible_immediately(monkeypatch):
 from tests.test_tab_daily import sample
 backend=Backend(False);at=app(monkeypatch,backend)
 # Same shape as the supplied Business Cube export, with a named source agent.
 content=sample(cause='AVVENUTO IMPIANTO TRAUMA').replace(b';Clinica;',b';Sapri;')
 monkeypatch.setattr(st,'file_uploader',lambda *a,**kw:SimpleNamespace(name='TAB.csv',getvalue=lambda:content))
 at.session_state['intervention_source']='Interventi TAB';at.run()
 assert not at.exception and not backend.writes
 next(b for b in at.button if b.label=='Conferma importazione TAB Trauma').click().run()
 assert not at.exception and len(backend.writes)==1
 assert backend.writes[0][1]['p_kind']=='IMPIANTO'
 assert backend.writes[0][1]['p_records'][0]['payload']['agent']=='Mariano Borrelli'
 assert [m.value for m in at.metric][:2]==['1','1']
 assert not {'interventi','righe_intervento','movimenti_magazzino','giacenze'}&set(backend.reads)
 st.cache_resource.clear();st.cache_data.clear()

def test_management_dashboard_uses_tab_and_has_no_surgeon_analysis(monkeypatch):
 backend=Backend();at=app(monkeypatch,backend,'core_app.py').run()
 assert not at.exception
 assert any('Controllo di Gestione' in x.value for x in at.title)
 assert [m.value for m in at.metric][:2]==['1','2']
 assert not any('chirurgo' in x.value.lower() for x in at.subheader)
 assert not backend.writes
 st.cache_resource.clear();st.cache_data.clear()

def test_tab_metadata_correction_is_audited_without_material_or_warehouse_mutation(monkeypatch):
 backend=Backend();at=app(monkeypatch,backend).run()
 before=deepcopy(backend.data['jj_recon_records'][2]['payload']['lines'])
 next(x for x in at.text_input if x.label=='CC verificata').set_value('VERIFICATA/1')
 next(x for x in at.checkbox if x.label=='Ho verificato i dati inseriti').check().run()
 next(b for b in at.button if b.label=='Salva verifica TAB').click().run()
 assert not at.exception and len(backend.writes)==1
 name,args=backend.writes[0]
 assert name=='jj_review_record' and args['p_action']=='EDIT' and args['p_note']
 assert args['p_payload']['encounter']=='VERIFICATA/1' and args['p_payload']['customer_code']=='00901'
 assert args['p_payload']['lines']==before
 assert not {'movimenti_magazzino','giacenze','righe_intervento','interventi'}&set(backend.reads)
 next(b for b in at.button if b.label=='Salva verifica TAB').click().run()
 assert len(backend.writes)==1
 st.cache_resource.clear();st.cache_data.clear()
