from copy import deepcopy
from io import BytesIO
import json
import openpyxl
import streamlit as st
from legacy_price_recovery import recovery_tables
from jj_report import excel_report
from tests.test_price_registry import PricesBackend,registry_app


def sample():
 return {'dettaglio':[{'codice_cliente':'00901','struttura':'Sapri','linea':'TRAUMA','cac':'100','ref':'413.016S','anno':2026,
  'dal':'2026-01-01','al':'2026-12-31','stato':'DA_VERIFICARE_PREZZI_STORICI','righe_origine':2,
  'provenienza':[{'riga_id':1,'prezzo':'8','fonte':'MANUALE','verificato_da':'old-user','verificato_il':'2026-10-01'},
    {'riga_id':2,'prezzo':'9','fonte':'MANUALE_DIREZIONE','verificato_da':'old-user','verificato_il':'2026-10-02'}]}]}


def test_report_preserves_original_prices_and_review_reasons_in_excel():
 data=sample();before=deepcopy(data);sheets=recovery_tables(data)
 assert sheets['Esiti recupero'][0]['Prezzi nello storico']=='8 | 9'
 assert sheets['Esiti recupero'][0]['Da verificare']
 assert len(sheets['Origini storiche'])==2 and sheets['Origini storiche'][0]['verificato_da']=='old-user'
 workbook=openpyxl.load_workbook(BytesIO(excel_report(sheets)))
 assert workbook['Origini storiche'].max_row==3
 assert data==before


def test_new_manual_verification_resolves_only_same_structure_line_presidio_and_period():
 data=sample();price={'codice_cliente':'00901','linea':'TRAUMA','cac':'100','ref':'413.016S','dal':'2026-01-01','al':'2026-12-31'}
 assert not recovery_tables(data,[price])['Esiti recupero'][0]['Da verificare']
 for changes in ({'codice_cliente':'OTHER'},{'linea':'PROTESICA'},{'cac':'200'},{'dal':'2026-06-01'}):
  assert recovery_tables(data,[{**price,**changes}])['Esiti recupero'][0]['Da verificare']
 assert recovery_tables(data,code='OTHER')['Esiti recupero']==[]


def test_registry_shows_recovery_evidence_without_running_import(monkeypatch):
 b=PricesBackend();b.data['audit_log']=[{'dettagli':json.dumps(sample())}]
 at=registry_app(monkeypatch,b)
 assert not at.exception and not b.writes
 assert any('1 prezzi storici da verificare' in x.value for x in at.warning)
 assert any(x.proto.label=='Scarica report completo recupero storico' for x in at.get('download_button'))
 frame=next(d.value for d in at.dataframe if 'Prezzi nello storico' in d.value.columns)
 assert frame['Da verificare'].sum()==1
 st.cache_resource.clear();st.cache_data.clear()


def test_report_read_error_does_not_block_price_registry(monkeypatch):
 b=PricesBackend();read=b.execute
 def execute():
  if b.name=='audit_log':raise RuntimeError('private connection info')
  return read()
 b.execute=execute
 at=registry_app(monkeypatch,b)
 assert not at.exception and any('Report di recupero non disponibile' in x.value for x in at.warning)
 assert not b.writes and not at.error
 st.cache_resource.clear();st.cache_data.clear()
