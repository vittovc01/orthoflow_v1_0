"""Assigned functions must work even when the user's primary role differs."""
from pathlib import Path
import pytest
import streamlit as st
import supabase
from streamlit.testing.v1 import AppTest
from tests.test_pages_smoke import ReadOnlyBackend


@pytest.mark.parametrize('page,permission',[
    ('01_WMS.py','LOGISTICA'),('02_QR_Scaffali.py','LOGISTICA'),
    ('03_Gestione_Scaffale.py','LOGISTICA'),('04_DDT_Carico_v2.py','LOGISTICA'),
    ('06_Gestione_Interventi.py','AMMINISTRAZIONE'),('07_Work_Implant.py','AMMINISTRAZIONE')])
@pytest.mark.parametrize('director',[False,True])
def test_assigned_function_is_not_blocked_by_primary_role(monkeypatch,page,permission,director):
    st.cache_resource.clear();st.cache_data.clear()
    monkeypatch.setattr(supabase,'create_client',lambda *a,**kw:ReadOnlyBackend())
    at=AppTest.from_file(Path(__file__).resolve().parents[1]/'pages'/page,default_timeout=30)
    at.secrets['SUPABASE_URL']='http://127.0.0.1:1'
    at.secrets['SUPABASE_SERVICE_KEY']='ci-only'
    for key,value in dict(user='test',ruolo='Agente',permessi=['DIREZIONE'] if director else [permission],agente_nome='',utente_id=1).items():
        at.session_state[key]=value
    at.run()
    assert not at.exception
    assert not any('riservat' in x.value.lower() or 'non autorizzato' in x.value.lower() for x in at.error)
    assert at.title
    st.cache_resource.clear();st.cache_data.clear()
