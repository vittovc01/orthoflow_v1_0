from copy import deepcopy
from datetime import date
from types import SimpleNamespace
import json
import pytest
import streamlit as st
from management_insights import monthly_structures,insights,ai_payload,payload_key,analyze
from tests.test_tab_management import report
from tests.test_jj_intervention_status import sources
from tests.test_tab_management_ui import Backend,app


def sample():
    base=sources();rows=[]
    for month,count in ((8,2),(9,4),(10,6),(11,8)):
        for n in range(count):
            r=deepcopy(base[2]);r['id']=len(rows)+10;r['source_key']=f'DOC-{month}-{n}'
            r['payload']['event_date']=f'2026-{month:02d}-01';r['payload']['encounter']=f'PRIVATE-CC-{month}-{n}'
            rows.append(r)
    return report(base[:2]+rows,[])


def test_monthly_counts_deduplicate_products_documents_and_keep_presidi_lines():
    r=sample();products=r['Prodotti TAB'];products.append(deepcopy(products[0]))
    other=deepcopy(products[0]);other['CAC']='OTHER';products.append(other)
    other=deepcopy(products[0]);other['Divisione']='PROTESICA';products.append(other)
    rows=monthly_structures(r)
    assert next(x for x in rows if x['Periodo']=='2026-08' and x['Divisione']=='TRAUMA' and x['Presidio']=='100')['Interventi']==2
    assert len(rows)==6
    assert len({(x['Divisione'],x['Presidio']) for x in rows})==3


def test_forecast_excludes_current_month_and_uses_three_completed_months():
    data=insights(sample(),date(2026,11,4));f=data['Previsioni'][0]
    assert f['Interventi stimati']==4
    assert f['Mesi base']=='2026-08, 2026-09, 2026-10'
    assert f['Mese stimato']=='2026-11'
    assert 0<=f['Scenario basso']<=f['Interventi stimati']<=f['Scenario alto']


@pytest.mark.parametrize('removed',[('2026-09',),('2026-10',),('2026-08','2026-09')])
def test_gaps_stale_or_short_history_never_filled_with_zero(removed):
    r=sample();r['Prodotti TAB']=[x for x in r['Prodotti TAB'] if x['Periodo'] not in removed]
    assert insights(r,date(2026,11,4))['Previsioni'][0]['Interventi stimati'] is None


def test_ai_payload_cannot_include_cc_lot_ref_or_raw_records():
    r=sample();before=deepcopy(r);data=insights(r,date(2026,11,4));payload=ai_payload(data)
    serialized=json.dumps(payload)
    assert all(x not in serialized for x in ('PRIVATE-CC','Cartella clinica','Lotto','ID intervento TAB','Documenti TAB','Prodotti TAB'))
    assert r==before
    assert payload_key(payload,'a')!=payload_key(payload,'b')
    changed=deepcopy(payload);changed['indicatori']['Interventi']+=1
    assert payload_key(payload,'a')!=payload_key(changed,'a')


def test_api_uses_bounded_private_request_and_rejects_partial_response():
    calls=[]
    def create(**kw):
        calls.append(kw)
        return SimpleNamespace(output_text='Analisi',status='completed',usage=SimpleNamespace(input_tokens=20,output_tokens=5))
    client=SimpleNamespace(responses=SimpleNamespace(create=create))
    result=analyze(ai_payload(insights(sample(),date(2026,11,4))),client,'configured-model')
    assert result['input_tokens']==20 and calls[0]['store'] is False
    assert calls[0]['max_output_tokens']==1800 and calls[0]['model']=='configured-model'
    with pytest.raises(ValueError):analyze({'huge':'x'*100001},client,'model')
    assert len(calls)==1
    client.responses.create=lambda **kw:SimpleNamespace(status='incomplete',output_text='Partial')
    with pytest.raises(ValueError):analyze({},client,'model')


def test_ai_is_on_demand_reuses_result_and_filter_change_invalidates(monkeypatch):
    import openai
    monkeypatch.setattr(openai,'OpenAI',lambda **kw:object())
    calls=[]
    def fake(*args):
        calls.append(args[0]);return {'testo':'Analisi verificata','modello':'test','input_tokens':3,'output_tokens':4}
    import management_insights_ui
    b=Backend();at=app(monkeypatch,b,'core_app.py');at.secrets['OPENAI_API_KEY']='fake'
    at.run();assert not at.exception and calls==[]
    next(x for x in at.radio if x.label=='Vista controllo di gestione').set_value('Analisi AI e previsioni').run()
    assert not at.exception and calls==[]
    monkeypatch.setattr(management_insights_ui,'analyze',fake)
    next(x for x in at.button if x.label=='Genera analisi e consigli AI').click().run()
    assert not at.exception and len(calls)==1
    at.run();assert not at.exception and len(calls)==1
    assert next(x for x in at.button if x.label=='Genera analisi e consigli AI').disabled
    assert any(x.value=='Analisi verificata' for x in at.markdown)
    next(x for x in at.selectbox if x.label=='Anno TAB').set_value('2026').run()
    # Same underlying numbers => same cached result, no extra billable request.
    assert len(calls)==1 and not b.writes
    st.cache_resource.clear();st.cache_data.clear()


def test_missing_api_key_does_not_hide_numerical_analysis(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    at=app(monkeypatch,Backend(),'core_app.py').run()
    next(x for x in at.radio if x.label=='Vista controllo di gestione').set_value('Analisi AI e previsioni').run()
    assert not at.exception
    assert next(x for x in at.button if x.label=='Genera analisi e consigli AI').disabled
    assert any('OPENAI_API_KEY' in x.value for x in at.info)
    assert any(x.value=='Priorità e previsioni' for x in at.subheader)
    st.cache_resource.clear();st.cache_data.clear()


def test_filtered_report_is_cached_but_price_refresh_invalidates(monkeypatch):
    import tab_management_ui as ui
    import management_insights_ui
    backend=Backend();at=app(monkeypatch,backend,'core_app.py').run()
    calls=[];original=ui.management_report
    def tracked(*a,**kw):calls.append(1);return original(*a,**kw)
    monkeypatch.setattr(ui,'management_report',tracked)
    at.run();assert not at.exception and calls==[]
    next(x for x in at.radio if x.label=='Vista controllo di gestione').set_value('Analisi AI e previsioni').run()
    assert not at.exception and calls==[]
    next(x for x in at.button if x.label=='Aggiorna dati TAB').click().run()
    assert not at.exception and len(calls)==1
    st.cache_resource.clear();st.cache_data.clear()


def test_api_failure_preserves_numeric_dashboard_and_allows_retry(monkeypatch):
    import management_insights_ui as ui
    import openai
    monkeypatch.setattr(openai,'OpenAI',lambda **kw:object())
    at=app(monkeypatch,Backend(),'core_app.py');at.secrets['OPENAI_API_KEY']='fake'
    at.run()
    next(x for x in at.radio if x.label=='Vista controllo di gestione').set_value('Analisi AI e previsioni').run()
    def failed(*args):raise RuntimeError('secret upstream error')
    monkeypatch.setattr(ui,'analyze',failed)
    next(x for x in at.button if x.label=='Genera analisi e consigli AI').click().run()
    assert not at.exception
    assert any('Analisi AI non disponibile' in w.value for w in at.warning)
    assert not next(x for x in at.button if x.label=='Genera analisi e consigli AI').disabled
    assert not any('secret upstream' in w.value for w in at.warning)
    assert at.dataframe and not at.session_state['management_ai_results']
    st.cache_resource.clear();st.cache_data.clear()
