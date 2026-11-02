from pathlib import Path
from types import SimpleNamespace
import streamlit as st
import supabase
from streamlit.testing.v1 import AppTest
from mobile.access import modules_for
from tests.test_jj_intervention_status import sources
from tests.test_jj_report import link

PAGE=Path(__file__).resolve().parents[1]/'pages/17_Stato_Interventi.py'

def test_status_page_is_read_only_downloads_and_refreshes_new_links(monkeypatch):
 dataset={'records':sources(),'links':[]};reads=[]
 class Backend:
  def table(self,name):self.name=name;return self
  def select(self,*a):return self
  def order(self,*a):return self
  def range(self,*a):return self
  def execute(self):
   reads.append(self.name)
   return SimpleNamespace(data=dataset['records' if self.name=='jj_recon_records' else 'links'])
  def rpc(self,*a):raise AssertionError('Status page must never write')
 st.cache_resource.clear();st.cache_data.clear()
 monkeypatch.setattr(supabase,'create_client',lambda *a,**kw:Backend())
 at=AppTest.from_file(str(PAGE),default_timeout=30)
 at.secrets['SUPABASE_URL']='http://127.0.0.1:1';at.secrets['SUPABASE_SERVICE_KEY']='fake'
 at.session_state['user']={'id':'test'};at.session_state['ruolo']='Admin';at.run()
 assert not at.exception
 assert [m.value for m in at.metric][:3]==['0','1','2']
 assert [x.proto.label for x in at.get('download_button')]==['Scarica Excel aggiornato']
 assert len(at.get('file_uploader'))==0
 dataset['links']=[link(2)]
 next(b for b in at.button if b.label=='Aggiorna dati').click().run()
 assert not at.exception and [m.value for m in at.metric][:3]==['1','0','0']
 assert reads.count('jj_recon_links')==2
 next(r for r in at.radio if r.label=='Divisione').set_value('PROTESICA').run()
 assert not at.exception and all(m.value=='0' for m in at.metric)
 st.cache_resource.clear();st.cache_data.clear()

def test_unauthorized_user_cannot_read_or_export_status(monkeypatch):
 def forbidden(*a,**kw):raise AssertionError('Unauthorized database access')
 monkeypatch.setattr(supabase,'create_client',forbidden)
 at=AppTest.from_file(str(PAGE),default_timeout=30)
 at.session_state['user']={'id':'test'};at.session_state['ruolo']='Corriere';at.session_state['permessi']=['CORRIERE'];at.run()
 assert not at.exception and any('non autorizzato' in x.value for x in at.error)
 assert not at.get('download_button')
 assert 'stato-interventi' not in {m['path'] for m in modules_for({'ruolo':'Agente','permessi':['AGENTE']})}
 assert 'stato-interventi' in {m['path'] for m in modules_for({'ruolo':'Admin','permessi':[]})}
 assert 'stato-interventi' in {m['path'] for m in modules_for({'ruolo':'Impiegato','permessi':['AMMINISTRAZIONE']})}
