"""The retired screen must never open a second reconciliation ledger."""
from pathlib import Path
import pytest
import supabase
from streamlit.testing.v1 import AppTest
from mobile.access import modules_for


@pytest.mark.parametrize('permissions,role', [(['DIREZIONE'],'Agente'),(['AMMINISTRAZIONE'],'Agente'),([], 'Admin')])
def test_only_guided_closure_is_offered(permissions, role, monkeypatch):
    paths=[m['path'] for m in modules_for({'ruolo':role,'permessi':permissions})]
    assert paths.count('chiusura-guidata')==1
    assert 'controllo-ordini-jj' not in paths
    def forbidden(*args,**kwargs):
        raise AssertionError('Retired screen must never access a database')
    monkeypatch.setattr(supabase,'create_client',forbidden)
    at=AppTest.from_file(Path(__file__).resolve().parents[1]/'pages/13_Controllo_Ordini_JJ.py')
    at.session_state['user']='test';at.session_state['ruolo']=role;at.session_state['permessi']=permissions
    at.run()
    assert not at.exception
    assert any('unica sezione' in item.value for item in at.info)
    assert not at.get('file_uploader') and not at.button and not at.dataframe


def test_streamlit_navigation_registers_only_one_reconciliation_page(monkeypatch):
    import streamlit as st
    registered=[]
    class Navigation:
        def run(self): pass
    def navigation(pages,**kwargs):
        registered.extend(p for group in pages.values() for p in group)
        return Navigation()
    monkeypatch.setattr(st,'navigation',navigation)
    at=AppTest.from_file(Path(__file__).resolve().parents[1]/'app.py')
    at.session_state['user']='test';at.session_state['ruolo']='Admin';at.run()
    assert not at.exception
    assert sum(p.url_path=='chiusura-guidata' for p in registered)==1
    assert not any(p.url_path=='controllo-ordini-jj' for p in registered)
