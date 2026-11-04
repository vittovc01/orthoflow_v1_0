from copy import deepcopy
from tab_analytics import chart_tables
from tests.test_tab_management import report,catalogs
from tests.test_jj_intervention_status import sources
from tests.test_tab_management_ui import Backend,app
import streamlit as st


def test_chart_counts_interventions_once_across_multiple_documents_products_and_lots():
 records=sources();original=records[2];other=deepcopy(original)
 other['id']=4;other['source_key']='OTHER';other['payload']['lines'][0]['lot']='OTHERLOT';records.append(other)
 result=report(records,[])
 charts=chart_tables(result)
 assert len(result['Interventi TAB'])==1
 assert charts['Per struttura'][0]['Interventi']==1
 assert charts['Per struttura'][0]['Pezzi']==4
 assert charts['Per periodo'][0]['Interventi']==1
 assert result['Per struttura'][0]['Interventi distinti']==1
 assert 'Interventi' not in result['Per struttura'][0]


def test_structure_counts_remain_visible_when_prices_are_missing_and_presidi_do_not_merge():
 records=sources();other=deepcopy(records[2]);other['id']=4;other['source_key']='SECOND'
 other['payload']['cac']='200';other['payload']['lines'][0]['cac']='200';records.append(other)
 cats=list(catalogs());cats[3]=[]
 result=report(records,[],cats)
 charts=chart_tables(result)
 assert len(charts['Per struttura'])==2
 assert sum(r['Interventi'] for r in charts['Per struttura'])==2
 assert all(r['Valore atteso valorizzato'] is None for r in charts['Per struttura'])
 assert {r['CAC'] for r in charts['Per struttura']}=={'100','200'}


def test_same_name_distinct_presidi_receive_distinct_chart_labels():
 rows=[{'Divisione':'TRAUMA','Struttura':'ASL','CAC':cac,'Interventi distinti':1,'Pezzi':2} for cac in ('100','200')]
 tables=chart_tables({'Per struttura':rows,'Per agente':[],'Per periodo':[]})
 assert {r['Struttura grafico'] for r in tables['Per struttura']}=={'ASL · 100','ASL · 200'}


def test_management_restores_graphs_and_structure_count_table_and_updates_filters(monkeypatch):
 b=Backend();at=app(monkeypatch,b,'core_app.py').run()
 assert not at.exception
 assert any(x.value=='Interventi per struttura' for x in at.subheader)
 assert any(x.value=='Andamento mensile degli interventi' for x in at.subheader)
 charts=at.get('vega_lite_chart')
 assert len(charts)>=5
 frame=next(d.value for d in at.dataframe if 'Struttura' in d.value.columns and 'Interventi' in d.value.columns)
 assert frame['Interventi'].sum()==1 and frame['Pezzi'].sum()==2
 assert not any('chirurg' in x.value.lower() for x in at.subheader)
 next(x for x in at.radio if x.label=='Linea TAB').set_value('PROTESICA').run()
 assert not at.exception and not at.get('vega_lite_chart')
 assert any('Nessun TAB caricato' in x.value for x in at.info)
 assert b.writes==[]
 st.cache_resource.clear();st.cache_data.clear()


def test_missing_prices_do_not_hide_activity_charts(monkeypatch):
 b=Backend();b.data['offerte_prezzi']=[]
 at=app(monkeypatch,b,'core_app.py').run()
 assert not at.exception
 assert len(at.get('vega_lite_chart'))==4
 assert any('Valori non disponibili' in x.value for x in at.info)
 frame=next(d.value for d in at.dataframe if 'Struttura' in d.value.columns and 'Interventi' in d.value.columns)
 assert frame['Interventi'].sum()==1
 assert frame['Valore atteso valorizzato'].isna().all()
 st.cache_resource.clear();st.cache_data.clear()


def test_trauma_and_protesica_counts_remain_separate_for_same_structure_and_cc():
 records=sources();other=deepcopy(records[2]);other.update(id=4,division='PROTESICA',source_key='PROTESICA')
 records.append(other)
 rows=chart_tables(report(records,[]))['Per struttura']
 assert {(r['Divisione'],r['Interventi']) for r in rows}=={('TRAUMA',1),('PROTESICA',1)}
 filtered=chart_tables(report(records,[],division='TRAUMA'))['Per struttura']
 assert len(filtered)==1 and filtered[0]['Interventi']==1 and filtered[0]['Divisione']=='TRAUMA'
