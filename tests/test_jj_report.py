from copy import deepcopy
from io import BytesIO
import openpyxl
import jj_report
from tests.test_jj_reconciliation import record


def sources():
 return [record('CHIUSURA',1),record('ORDINE',2),record('IMPIANTO',3,encounter='0007')]


def link(q=1,implant=3,id=1):
 return {'id':id,'closure_id':1,'closure_line':'line','order_id':2,'order_line':'line','implant_id':implant,'implant_line':'line','quantity':q,'revoked_at':None,'method':'MANUALE','actor':'test','created_at':'2026-11-02'}


def test_partial_report_preserves_all_sources_and_explains_close_block():
 records=sources();report=jj_report.build_report(records,[link()],1)
 assert len(report['Associazioni'])==1
 assert report['status']['open_quantity']==1
 assert report['status']['open_value']==10
 assert not report['status']['can_close']
 assert report['Blocchi chiusura'] and '1 pezzi' in report['Blocchi chiusura'][0]['Motivo']
 assert {r['Fonte'] for r in report['Non associati']}=={'CHIUSURA','ORDINE','IMPIANTO'}
 row=report['Righe chiusura'][0]
 assert row['Stato']=='PARZIALE' and row['Quantità residua']==1 and row['CC associate']=='0007'
 assert sum(row[k] for k in ['Valore associato','Valore residuo'])==row['Totale riga']


def test_price_difference_is_quantity_weighted_once_despite_two_cc_links():
 records=sources();records[1]['payload']['lines'][0].update(price=None,total='19.98')
 records[2]['payload']['lines'][0]['quantity']=1
 other=deepcopy(records[2]);other['id']=4;other['payload']['encounter']='0008';records.append(other)
 report=jj_report.build_report(records,[link(1),link(1,4,2)],1)
 assert report['status']['can_close'] # Price warnings do not silently change closure rules.
 assert report['status']['price_differences']==1
 price=report['Prezzi da verificare'][0]
 assert price['Prezzo ordine']==9.99 and price['Quantità confrontata']==2
 assert abs(price['Scostamento sulla quantità']-.02)<1e-8
 assert len(report['Associazioni'])==2
 assert all(r['Prezzo ordine']==9.99 for r in report['Associazioni'])


def test_pending_linked_source_blocks_closure_but_unrelated_month_does_not():
 records=sources();other=record('CHIUSURA',5);other['source_key']='2026-11';records.append(other)
 report=jj_report.build_report(records,[link(2)],1)
 assert report['status']['can_close']
 records[1]['pending_payload']={'lines':[]}
 report=jj_report.build_report(records,[link(2)],1)
 assert report['status']['pending_revisions']==1 and not report['status']['can_close']
 assert 'revisione' in report['Blocchi chiusura'][0]['Motivo']


def test_missing_order_is_not_called_a_price_difference_or_invented_billing():
 records=sources();records.pop(1)
 report=jj_report.build_report(records,[],1)
 assert report['status']['price_differences']==0 and report['status']['price_unverified']==1
 assert report['Prezzi da verificare'][0]['Esito']=='NON CONFRONTABILE'
 assert 'Distinta ordine mancante' in report['Righe chiusura'][0]['Motivo / azione']
 assert any('altri mesi' in str(r) for r in report['Non associati'] if r['Fonte']=='IMPIANTO')


def test_returns_and_economic_adjustments_are_preserved_without_implant_quantities():
 records=sources()
 records[0]['payload']['lines'].append({'key':'return','ref':'RET','quantity':-1,'price':'10','total':'-10','cac':'100'})
 records[0]['payload']['economic_rows']=[{'codice':'REBATE','nis':'-5','invoiced_sales':'-5','raw_data':{'Order Type[O. Sub Type]':'Rebate'}}]
 report=jj_report.build_report(records,[link(2)],1)
 assert report['status']['can_close'] and len(report['Resi e rettifiche'])==2
 assert sum(r['Fatturato'] for r in report['Resi e rettifiche'])==-15


def test_application_export_is_complete_and_text_cannot_become_a_formula():
 records=sources();records[1]['payload']['lines'][0]['description']='=2+2'
 report=jj_report.build_report(records,[link()],1)
 content=jj_report.excel_report(report)
 workbook=openpyxl.load_workbook(BytesIO(content),data_only=False)
 assert set(workbook.sheetnames)==set(report)-{'status'}
 rows=list(workbook['Associazioni'].values);idx=rows[0].index('Descrizione')
 assert rows[1][idx]=='=2+2' and workbook['Associazioni'].cell(2,idx+1).data_type=='s'
 assert workbook['Non associati'].max_row==4
 assert workbook['Blocchi chiusura'].max_row==2


def test_runtime_refresh_recovers_stale_report_helper(monkeypatch):
 import jj_report_runtime
 monkeypatch.delattr(jj_report,'build_report')
 jj_report_runtime._signature=None
 assert callable(jj_report_runtime.current_reports().build_report)
