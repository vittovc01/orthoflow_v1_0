import pytest
from pathlib import Path
from types import SimpleNamespace
import streamlit as st
import supabase
from streamlit.testing.v1 import AppTest

def test_division_switch_separates_uploads_templates_and_final_acceptance(monkeypatch):
 from copy import deepcopy
 from tests.test_jj_reconciliation import record
 records=[record(kind,i) for kind,i in [('CHIUSURA',1),('ORDINE',2),('IMPIANTO',3)]]
 other=deepcopy(records)
 for r in other:r['id']+=3;r['division']='PROTESICA'
 records+=other
 links=[{'id':n,'closure_id':1+d,'order_id':2+d,'implant_id':3+d,'closure_line':'line','order_line':'line','implant_line':'line','quantity':2,'revoked_at':None,'method':'MANUALE','actor':'test','created_at':'2026-11-02'} for n,d in [(1,0),(2,3)]]
 class Backend:
  def table(self,name):self.name=name;return self
  def select(self,*a):return self
  def order(self,*a):return self
  def range(self,*a):return self
  def execute(self):return SimpleNamespace(data=records if self.name=='jj_recon_records' else links if self.name=='jj_recon_links' else [{'codice_cliente':'00901','descrizione':'Sapri'}])
  def rpc(self,*a):raise AssertionError('No writes while changing division')
 st.cache_resource.clear();st.cache_data.clear()
 monkeypatch.setattr(supabase,'create_client',lambda *a,**kw:Backend())
 at=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'pages/16_Chiusura_Guidata.py'),default_timeout=30)
 at.secrets['SUPABASE_URL']='http://127.0.0.1:1';at.secrets['SUPABASE_SERVICE_KEY']='fake'
 at.session_state['user']={'id':'test'};at.session_state['ruolo']='Admin';at.run()
 assert not at.exception
 assert any(x.proto.label=='Scarica modello ordini Trauma' for x in at.get('download_button'))
 assert all(x.key.endswith('_TRAUMA') for x in at.get('file_uploader'))
 at.checkbox[0].check().run()
 next(r for r in at.radio if r.label=='Area di chiusura').set_value('PROTESICA').run()
 assert not at.exception
 assert all(x.key.endswith('_PROTESICA') for x in at.get('file_uploader'))
 assert any(x.proto.label=='Scarica modello ordini Protesica' for x in at.get('download_button'))
 assert not at.checkbox[0].value
 assert next(b for b in at.button if b.label=='Conferma chiusura del mese').disabled
 assert all(m.value=='1' for m in list(at.metric)[:3])
 st.cache_resource.clear();st.cache_data.clear()

def test_guided_page_renders_three_uploads_without_writes(monkeypatch):
 class Backend:
  def table(self,*a):return self
  def select(self,*a):return self
  def order(self,*a):return self
  def range(self,*a):return self
  def execute(self):return SimpleNamespace(data=[])
  def rpc(self,*a):raise AssertionError('No writes during page render')
 st.cache_resource.clear();st.cache_data.clear()
 # Simulate the live worker's old cached module before opening the new page.
 import jj_reconciliation, jj_runtime
 monkeypatch.delattr(jj_reconciliation,'allocation_plan',raising=False)
 jj_runtime._signatures.clear()
 monkeypatch.setattr(supabase,'create_client',lambda *a,**kw:Backend())
 page=Path(__file__).resolve().parents[1]/'pages/16_Chiusura_Guidata.py'
 at=AppTest.from_file(str(page),default_timeout=30)
 at.secrets['SUPABASE_URL']='http://127.0.0.1:1';at.secrets['SUPABASE_SERVICE_KEY']='fake'
 at.session_state['user']={'id':'test'};at.session_state['ruolo']='Admin'
 at.run()
 assert not at.exception
 assert any('Chiusura guidata' in t.value for t in at.title)
 assert len(at.get('file_uploader'))==2
 assert len(at.metric)==3 and all(m.value=='0' for m in at.metric)
 assert any('Nessun dato caricato' in item.value for item in at.info)
 assert not at.subheader
 assert not any('Conferma collegamenti' in b.label for b in at.button)
 st.cache_resource.clear();st.cache_data.clear()


@pytest.mark.parametrize('has_links',[False,True])
def test_guided_page_renders_real_proposals_and_month_review(monkeypatch,has_links):
 line={'key':'L','ref':'413.016S','quantity':1,'cac':'100','customer':'Sapri','po':'PO1','invoice':'F1','date':'2026-10-01','price':'10','total':'10','lot':''}
 records=[{'id':i,'kind':kind,'division':'TRAUMA','source_key':str(i),'pending_payload':None,'closed_at':None,
  'payload':{'cac':'100','customer':'Sapri','encounter':'003','event_date':'2026-09-01','reference':'cc 1 del 01/09/2026','lines':[dict(line)]}}
  for i,kind in [(1,'CHIUSURA'),(2,'ORDINE'),(3,'IMPIANTO')]]
 calls=[]
 class Backend:
  def table(self,name):self.name=name;return self
  def select(self,*a):return self
  def order(self,*a):return self
  def range(self,*a):return self
  def execute(self):return SimpleNamespace(data=records if self.name=='jj_recon_records' else ([{'id':1,'closure_id':1,'closure_line':'L','order_id':2,'order_line':'L','implant_id':3,'implant_line':'L','quantity':1,'method':'MANUALE','actor':'reviewer','created_at':'2026-11-02','revoked_at':None}] if has_links else []))
  def rpc(self,name,args):
   calls.append((name,args))
   return SimpleNamespace(execute=lambda:SimpleNamespace(data=1))
 st.cache_resource.clear();st.cache_data.clear()
 monkeypatch.setattr(supabase,'create_client',lambda *a,**kw:Backend())
 at=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'pages/16_Chiusura_Guidata.py'),default_timeout=30)
 at.secrets['SUPABASE_URL']='http://127.0.0.1:1';at.secrets['SUPABASE_SERVICE_KEY']='fake'
 at.session_state['user']={'id':'test'};at.session_state['ruolo']='Admin';at.run()
 assert not at.exception
 assert any(b.label=='Conferma tutta la proposta' for b in at.button)==(not has_links)
 if not has_links:
  draft=next(d.value for d in at.dataframe if 'Escludi' in d.value.columns)
  assert not draft['Escludi'].any()
  assert 'Conferma' not in draft.columns
 assert any('Cartella clinica' in d.value.columns for d in at.dataframe)
 if has_links:
  confirmed=next(d.value for d in at.dataframe if 'Cartella clinica' in d.value.columns)
  assert confirmed.iloc[0]['Cartella clinica']=='003'
 assert any(b.label=='Conferma chiusura del mese' for b in at.button)
 assert len(at.checkbox)==(1 if has_links else 2) and not any(c.value for c in at.checkbox)
 assert calls==[]
 if has_links:
  at.checkbox[0].check().run()
  next(b for b in at.button if b.label=='Conferma chiusura del mese').click().run()
  assert not at.exception and len(calls)==1
  assert calls[0][1]['p_action']=='CLOSE' and calls[0][1]['p_note']
 else:
  assert next(b for b in at.button if b.label=='Conferma chiusura del mese').disabled
 if not has_links:
  next(b for b in at.button if b.label=='Conferma tutta la proposta').click().run()
  assert calls==[] and any('Conferma di aver verificato' in e.value for e in at.error)
  at.checkbox[0].check()
  next(b for b in at.button if b.label=='Conferma tutta la proposta').click().run()
  assert not at.exception and len(calls)==1
  assert calls[0][0]=='jj_confirm_links'
  assert calls[0][1]['p_links'][0]['quantity']==1
  assert calls[0][1]['p_links'][0]['proposal_criterion']=='UNIQUE_CANDIDATE'
  next(r for r in at.radio if r.label=='Modalità di abbinamento').set_value('Scelta manuale').run()
  at.checkbox[0].check()
  next(b for b in at.button if b.label=='Conferma collegamenti selezionati').click().run()
  assert len(calls)==1
  assert any('Nessun collegamento da salvare' in w.value for w in at.warning)
 st.cache_resource.clear();st.cache_data.clear()
