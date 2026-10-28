from pathlib import Path
from types import SimpleNamespace
import streamlit as st
from streamlit.testing.v1 import AppTest
import supabase

def test_division_selection_changes_forecast_and_consuntivo(monkeypatch):
    tables={
      'interventi':[
        {'id':1,'data_intervento':'2026-10-10','linea':'TRAUMA','struttura':'Clinica','codice_cliente':'C','cartella_clinica':'TEST-1'},
        {'id':2,'data_intervento':'2026-10-10','linea':'PROTESICA','struttura':'Clinica','codice_cliente':'C','cartella_clinica':'TEST-2'}],
      'righe_intervento':[
        {'id':1,'intervento_id':1,'totale':10,'quantita':1,'prezzo':10},
        {'id':2,'intervento_id':2,'totale':100,'quantita':1,'prezzo':100}],
      'chiusure_mensili_johnson':[
        {'id':1,'mese':'2026-10-01','divisione':'TRAUMA','nome_file':'trauma.xlsx','importo_totale_jj':12,'nis_totale':12,'invoiced_sales_totale':12},
        {'id':2,'mese':'2026-10-01','divisione':'PROTESICA','nome_file':'protesi.xlsx','importo_totale_jj':120,'nis_totale':120,'invoiced_sales_totale':120}],
    }
    class Backend:
        def table(self,name): self.name=name;return self
        def select(self,*args):return self
        def eq(self,*args):return self
        def execute(self):return SimpleNamespace(data=tables.get(self.name,[]))
    st.cache_resource.clear()
    monkeypatch.setattr(supabase,'create_client',lambda *a,**k:Backend())
    page=Path(__file__).resolve().parents[1]/'pages/13_Controllo_Ordini_JJ.py'
    app=AppTest.from_file(str(page),default_timeout=30)
    app.secrets['SUPABASE_URL']='http://127.0.0.1:1'
    app.secrets['SUPABASE_SERVICE_KEY']='fake'
    app.session_state['user']={'id':'test'}
    app.session_state['ruolo']='Admin'
    app.run()
    assert not app.exception
    assert any(m.label=='Chiusura J&J caricata' and m.value=='€ 12.00' for m in app.metric)
    app.selectbox(key='close_div').select('PROTESICA').run()
    assert not app.exception
    assert any(m.label=='Chiusura J&J caricata' and m.value=='€ 120.00' for m in app.metric)
    assert any(m.label=='Previsione P.M. Medical' and m.value=='€ 100.00' for m in app.metric)
    assert not any('riconciliazione automatica' in b.label.lower() for b in app.button)
    st.cache_resource.clear()
