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
 assert not any('Conferma collegamenti' in b.label for b in at.button)
 st.cache_resource.clear();st.cache_data.clear()
