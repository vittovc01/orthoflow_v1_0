"""Reproduce older imported TAB modules surviving a Streamlit page rerun."""
import importlib
import tab_runtime
import tab_price_anomalies
import tab_management_ui
from tests.test_tab_price_anomalies import Backend,page


def test_warm_anomaly_page_recovers_new_form_and_search_without_process_restart(monkeypatch):
    tab_runtime._signatures.clear()
    monkeypatch.setattr(tab_price_anomalies,'render_tab_price_anomalies',lambda *args:None)
    monkeypatch.setattr(tab_management_ui,'tab_catalogs',lambda client:None)
    backend=Backend();backend.data['offerte_prezzi']=[]
    at=page(monkeypatch,backend).run()
    assert not at.exception
    assert any(x.label=='Prezzo unitario verificato (€)' for x in at.number_input)
    assert any(x.label=='Cerca REF o descrizione' for x in at.text_input)
    assert any(x.label=='Struttura successiva con anomalie' for x in at.button)
    assert not backend.writes


def test_tab_reloads_downstream_bindings_only_after_source_changes(monkeypatch):
    reload=importlib.reload;calls=[]
    def tracked(module):
        calls.append(module.__name__);return reload(module)
    tab_runtime.current_tab();monkeypatch.setattr(importlib,'reload',tracked)
    tab_runtime.current_tab();assert calls==[]
    tab_runtime._signatures['tab_management']=None
    tab_runtime.current_tab()
    assert calls==['tab_management','management_insights','management_insights_ui','tab_analytics','tab_management_ui','tab_price_anomalies']
    calls.clear();tab_runtime.current_management();assert calls==[]
