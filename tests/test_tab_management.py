from copy import deepcopy
from io import BytesIO
import openpyxl
from tab_management import management_report
from jj_intervention_status import build_status
from jj_report import excel_report
from tests.test_jj_intervention_status import sources
from tests.test_jj_report import link

def catalogs():
 return ([{'codice_cliente':'00901','descrizione':'Sapri'}],
  [{'id':1,'linea':'TRAUMA','stato_record':'Attivo','data_inizio':'2026-01-01','data_fine':'2026-12-31'}],
  [{'id':1,'offerta_id':1,'codice_cliente':'00901'}],
  [{'id':1,'offerta_id':1,'codice':'413.016S','prezzo':'8'}])

def report(records=None,links=None,cats=None,**filters):
 return management_report(records or sources(),links if links is not None else [link(2)],*(cats or catalogs()),build_status,**filters)

def test_management_uses_tab_quantities_offer_and_actual_invoice_as_distinct_measures():
 r=report()
 assert len(r['Interventi TAB'])==1 and r['Interventi TAB'][0]['Pezzi impiantati']==2
 assert r['Prodotti TAB'][0]['Prezzo offerta']==8 and r['Per struttura'][0]['Valore atteso valorizzato']==16
 assert r['Per struttura'][0]['Valore fatturato associato']==20
 assert r['Prezzi da verificare'][0]['Scostamento sulla quantità']==4
 assert r['Per periodo'][0]['Periodo']=='2026-09'
 wb=openpyxl.load_workbook(BytesIO(excel_report(r)))
 assert set(wb.sheetnames)==set(r)

def test_offer_validity_division_and_ambiguity_are_checked_without_guessing():
 cats=catalogs();cats[1][0]['data_fine']='2025-12-31'
 assert report(cats=cats)['Prodotti TAB'][0]['Prezzo offerta'] is None
 cats=catalogs();cats[1].append({**cats[1][0],'id':2});cats[2].append({'offerta_id':2,'codice_cliente':'00901'});cats[3].append({'offerta_id':2,'codice':'413.016S','prezzo':'9'})
 r=report(cats=cats)
 assert r['Prodotti TAB'][0]['Valore atteso'] is None
 assert r['Per struttura'][0]['Righe senza prezzo']==1
 assert 'prezzi diversi' in r['Prezzi da verificare'][0]['Motivo / azione']
 cats[1][1]['linea']='PROTESICA'
 assert report(cats=cats)['Prodotti TAB'][0]['Prezzo offerta']==8
 cats[1][0]['stato_record']='Archiviato'
 assert report(cats=cats)['Prodotti TAB'][0]['Prezzo offerta'] is None

def test_ambiguous_customer_or_normalized_ref_is_not_priced():
 cats=catalogs();cats[0].append({'codice_cliente':'00902','descrizione':'Sapri'})
 assert report(cats=cats)['Prodotti TAB'][0]['Codice struttura']==''
 cats=list(catalogs());cats[3]=[{'offerta_id':1,'codice':'12.34','prezzo':'8'},{'offerta_id':1,'codice':'123.4','prezzo':'8'}]
 records=sources();records[2]['payload']['lines'][0]['ref']='1234'
 r=report(records,[],cats)
 assert 'REF ambiguo' in r['Prodotti TAB'][0]['Motivo / azione']

def test_multiple_tab_documents_count_one_cc_and_agent_filter_recalculates_detail():
 records=sources();records[2]['payload']['lines'][0]['quantity']=1;records[2]['payload']['agent_code']='4'
 other=deepcopy(records[2]);other['id']=4;other['source_key']='other';other['payload']['agent_code']='8';records.append(other)
 r=report(records,[link(1),link(1,4,2)])
 assert len(r['Interventi TAB'])==1 and r['Per struttura'][0]['Pezzi']==2
 assert {x['Agente'] for x in r['Per agente']}=={'Mariano Borrelli','Francesco Cirillo'}
 r=report(records,[link(1),link(1,4,2)],agent='Mariano Borrelli')
 assert len(r['Prodotti TAB'])==1 and r['Interventi TAB'][0]['Pezzi impiantati']==1
 assert r['Interventi TAB'][0]['Valore atteso valorizzato']==8

def test_offer_update_recalculates_expected_amount_without_changing_source_quantities():
 records=sources();before=deepcopy(records);cats=catalogs()
 assert report(records,cats=cats)['Per struttura'][0]['Valore atteso valorizzato']==16
 cats[3][0]['prezzo']='9'
 assert report(records,cats=cats)['Per struttura'][0]['Valore atteso valorizzato']==18
 assert records==before

def test_unknown_invoice_value_is_visible_and_not_reported_as_zero():
 records=sources();records[0]['payload']['lines'][0].update(price=None,total=None)
 r=report(records)
 assert r['Prodotti TAB'][0]['Valore fatturato associato'] is None
 assert r['Per struttura'][0]['Valore fatturato associato'] is None
 assert any(x['Esito']=='PREZZO FATTURA MANCANTE' for x in r['Prezzi da verificare'])

def test_large_tab_prices_do_not_reparse_offer_dates_for_every_product(monkeypatch):
 import tab_management
 parse=tab_management.date;calls=[]
 def tracked(value):calls.append(value);return parse(value)
 monkeypatch.setattr(tab_management,'date',tracked)
 records=[sources()[2]];base=records[0]['payload']['lines'][0]
 records[0]['payload']['lines']=[{**base,'key':str(i),'ref':'SKU'+str(i),'quantity':1} for i in range(2000)]
 cats=list(catalogs());cats[3]=[{'offerta_id':1,'codice':'SKU'+str(i),'prezzo':'8'} for i in range(2000)]
 r=report(records,[],cats)
 assert len(r['Prodotti TAB'])==2000 and r['Per struttura'][0]['Valore atteso valorizzato']==16000
 assert len(calls)==2
