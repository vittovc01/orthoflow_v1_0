"""Assigned functions must work even when the user's primary role differs."""
from pathlib import Path
import pytest
import streamlit as st
import supabase
from streamlit.testing.v1 import AppTest
from tests.test_pages_smoke import ReadOnlyBackend


@pytest.mark.parametrize('user,role,permissions,allowed',[
    ('','Admin',['DIREZIONE'],False),
    ('test','Agente',['AGENTE'],False),
    ('test','Admin',[],True),
    ('test','Agente',['DIREZIONE'],True),
])
def test_ocr_acceptance_requires_director_and_does_not_write(monkeypatch,user,role,permissions,allowed):
    import openai
    def forbidden(*args, **kwargs):
        raise AssertionError('Opening the OCR acceptance page must not create clients or write data')
    monkeypatch.setattr(supabase,'create_client',forbidden)
    monkeypatch.setattr(openai,'OpenAI',forbidden)
    at=AppTest.from_file(Path(__file__).resolve().parents[1]/'pages'/'15_OCR_Collaudo.py',default_timeout=30)
    at.secrets['OPENAI_API_KEY']='ci-only-not-a-real-key'
    at.secrets['ENABLE_AI_OCR']='true'
    for key,value in dict(user=user,ruolo=role,permessi=permissions).items():
        at.session_state[key]=value
    at.run()
    assert not at.exception
    if allowed:
        assert at.title and any('non scarica' in x.value for x in at.info)
        assert next(b for b in at.button if b.label == 'Analizza senza scaricare').disabled
        assert not next(b for b in at.button if b.label == 'Verifica servizio AI senza foto').disabled
    else:
        assert any('non autorizzato' in x.value.lower() for x in at.error)
        assert not at.title


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


@pytest.mark.parametrize('permissions,expected',[
    (['LOGISTICA'],['Inventario']),
    (['AMMINISTRAZIONE'],['Clienti','Offerte','Archivio impianti','KPI e Fatturato']),
    (['LOGISTICA','AMMINISTRAZIONE'],['Inventario','Clienti','Offerte','Archivio impianti','KPI e Fatturato'])])
def test_management_menu_excludes_director_tools(monkeypatch,permissions,expected):
    st.cache_resource.clear();st.cache_data.clear()
    monkeypatch.setattr(supabase,'create_client',lambda *a,**kw:ReadOnlyBackend())
    at=AppTest.from_file(Path(__file__).resolve().parents[1]/'core_app.py',default_timeout=30)
    at.secrets['SUPABASE_URL']='http://127.0.0.1:1'
    at.secrets['SUPABASE_SERVICE_KEY']='ci-only'
    for key,value in dict(user='test',ruolo='Agente',permessi=permissions,agente_nome='',utente_id=1).items():
        at.session_state[key]=value
    at.run()
    assert not at.exception
    menu=next(x for x in at.radio if x.label=='Menu')
    assert menu.options==expected
    st.cache_resource.clear();st.cache_data.clear()
