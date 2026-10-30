from pathlib import Path
from types import SimpleNamespace
import streamlit as st
import supabase
from streamlit.testing.v1 import AppTest

def test_guided_page_renders_three_uploads_without_writes(monkeypatch):
 class Backend:
  def table(self,*a):return self
  def select(self,*a):return self
  def order(self,*a):return self
  def range(self,*a):return self
  def execute(self):return SimpleNamespace(data=[])
  def rpc(self,*a):raise AssertionError('No writes during page render')
 st.cache_resource.clear();st.cache_data.clear()
 monkeypatch.setattr(supabase,'create_client',lambda *a,**kw:Backend())
 page=Path(__file__).resolve().parents[1]/'pages/16_Chiusura_Guidata.py'
 at=AppTest.from_file(str(page),default_timeout=30)
 at.secrets['SUPABASE_URL']='http://127.0.0.1:1';at.secrets['SUPABASE_SERVICE_KEY']='fake'
 at.session_state['user']={'id':'test'};at.session_state['ruolo']='Admin'
 at.run()
 assert not at.exception
 assert any('Chiusura guidata' in t.value for t in at.title)
 assert len(at.get('file_uploader'))==3
 assert len(at.metric)==3 and all(m.value=='0' for m in at.metric)
 assert any('Nessun dato caricato' in item.value for item in at.info)
 assert not at.subheader
 assert not any('Conferma collegamenti' in b.label for b in at.button)
 st.cache_resource.clear();st.cache_data.clear()


def test_guided_page_renders_real_proposals_and_month_review(monkeypatch):
 line={'key':'L','ref':'413.016S','quantity':1,'cac':'100','customer':'Sapri','po':'PO1','invoice':'F1','date':'2026-10-01','price':'10','total':'10','lot':''}
 records=[{'id':i,'kind':kind,'division':'TRAUMA','source_key':str(i),'pending_payload':None,'closed_at':None,
  'payload':{'cac':'100','customer':'Sapri','event_date':'2026-09-01','reference':'cc 1 del 01/09/2026','lines':[dict(line)]}}
  for i,kind in [(1,'CHIUSURA'),(2,'ORDINE'),(3,'IMPIANTO')]]
 class Backend:
  def table(self,name):self.name=name;return self
  def select(self,*a):return self
  def order(self,*a):return self
  def range(self,*a):return self
  def execute(self):return SimpleNamespace(data=records if self.name=='jj_recon_records' else [])
  def rpc(self,*a):raise AssertionError('No automatic confirmation')
 st.cache_resource.clear();st.cache_data.clear()
 monkeypatch.setattr(supabase,'create_client',lambda *a,**kw:Backend())
 at=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'pages/16_Chiusura_Guidata.py'),default_timeout=30)
 at.secrets['SUPABASE_URL']='http://127.0.0.1:1';at.secrets['SUPABASE_SERVICE_KEY']='fake'
 at.session_state['user']={'id':'test'};at.session_state['ruolo']='Admin';at.run()
 assert not at.exception
 assert any(b.label=='Conferma collegamenti selezionati' for b in at.button)
 assert any(b.label=='Conferma chiusura del mese' for b in at.button)
 assert len(at.checkbox)==2 and not any(c.value for c in at.checkbox)
 st.cache_resource.clear();st.cache_data.clear()
