from copy import deepcopy
from io import BytesIO
import openpyxl
from jj_intervention_status import build_status
from jj_report import excel_report
from tests.test_jj_reconciliation import record
from tests.test_jj_report import link

def sources():
 return [record('CHIUSURA',1),record('ORDINE',2),record('IMPIANTO',3,encounter='0007')]

def test_complete_cc_spanning_documents_is_one_intervention_and_price_issue_is_not_doubled():
 records=sources();records[2]['payload']['lines'][0]['quantity']=1
 other=record('IMPIANTO',4,quantity=1,encounter='0007');records.append(other)
 records[1]['payload']['lines'][0].update(price=None,total='19.98')
 report=build_status(records,[link(1),link(1,4,2)])
 assert report['status']['closed']==1 and report['status']['open']==0
 row=report['Interventi chiusi'][0]
 assert row['Cartella clinica']=='0007' and row['Pezzi chiusi']==2 and row['Valore fatturato associato']==20
 assert len(report['Dettaglio prodotti'])==2 and len(report['Ordini e fatture'])==2
 assert row['Differenze prezzo']==1 and report['status']['price_differences']==1
 assert abs(report['Prezzi da verificare'][0]['Scostamento sulla quantità']-.02)<1e-8
 wb=openpyxl.load_workbook(BytesIO(excel_report(report)),data_only=False)
 assert set(wb.sheetnames)==set(report)-{'status'}
 assert wb['Interventi chiusi'].max_row==2 and wb['Dettaglio prodotti'].max_row==3

def test_partial_intervention_and_revoked_links_do_not_look_closed():
 records=sources();revoked=link(2,id=2);revoked['revoked_at']='2026-11-02'
 report=build_status(records,[link(1),revoked])
 assert report['status']['closed']==0 and report['status']['remaining_quantity']==1
 assert report['Interventi da chiudere'][0]['Stato']=='PARZIALMENTE CHIUSO'
 assert report['Interventi da chiudere'][0]['Pezzi associati']==1

def test_invoice_in_later_year_still_closes_earlier_intervention():
 records=sources();records[0]['source_key']='2027-01';records[0]['payload']['lines'][0]['date']='2027-01-10'
 result=build_status(records,[link(2)],year='2026')
 assert result['status']['closed']==1
 assert result['Interventi chiusi'][0]['Mesi fatturazione']=='2027-01'
 assert build_status(records,[link(2)],year='2025')['status']['closed']==0

def test_same_cc_can_be_closed_by_invoices_in_two_months():
 records=sources();records[0]['source_key']='2026-10';records[0]['payload']['lines'][0]['quantity']=1
 records[1]['payload']['lines'][0]['invoice']=''
 other=deepcopy(records[0]);other['id']=4;other['source_key']='2026-11';other['payload']['lines'][0]['invoice']='F2';records.append(other)
 second=link(1,id=2);second['closure_id']=4
 result=build_status(records,[link(1),second])
 assert result['status']['closed']==1
 assert result['Interventi chiusi'][0]['Fatture']=='F1, F2'
 assert result['Interventi chiusi'][0]['Mesi fatturazione']=='2026-10, 2026-11'

def test_pending_revision_or_placeholder_invoice_is_never_closed():
 records=sources();records[1]['pending_payload']={'lines':[]}
 result=build_status(records,[link(2)])
 assert result['status']['closed']==0 and 'Revisione' in result['Interventi da chiudere'][0]['Motivo / azione']
 records[1].pop('pending_payload');records[0]['payload']['lines'][0]['invoice']='0';records[1]['payload']['lines'][0]['invoice']=''
 result=build_status(records,[link(2)])
 assert result['status']['closed']==0 and 'fattura' in result['Interventi da chiudere'][0]['Motivo / azione']

def test_cross_division_and_overallocated_links_are_flagged_not_counted():
 records=sources();records[1]['division']='PROTESICA'
 result=build_status(records,[link(2)])
 assert result['status']['closed']==0 and result['status']['remaining_quantity']==2
 assert 'discordante' in result['Interventi da chiudere'][0]['Motivo / azione']
 records[1]['division']='TRAUMA'
 result=build_status(records,[link(2),link(1,id=2)])
 assert result['status']['closed']==0 and 'eccessiva' in result['Interventi da chiudere'][0]['Motivo / azione']
 assert build_status(records,[link(2)],division='PROTESICA')['status']['closed']==0

def test_no_tab_or_missing_order_never_silently_produces_healthy_price_result():
 records=sources();records.pop(1)
 result=build_status(records,[])
 assert result['status']['price_differences']==0 and result['status']['price_missing']==1
 assert result['Prezzi da verificare'][0]['Esito']=='DISTINTA ORDINE MANCANTE'
 result=build_status(records[:1],[])
 assert result['status']['closed']==0 and len(result['Documenti da associare'])==1
 assert result['status']['price_missing']==1

def test_unidentified_documents_stay_separate_and_visible_with_year_filter():
 records=sources();records[2]['payload'].update(encounter='',event_date='')
 other=deepcopy(records[2]);other['id']=4;other['source_key']='other';records.append(other)
 result=build_status(records,[],year='2026')
 assert result['status']['open']==2
 assert all('clinica mancante' in r['Motivo / azione'] for r in result['Interventi da chiudere'])

def test_structure_filter_keeps_all_documents_of_the_same_cc_and_cac():
 records=sources();records[2]['payload']['lines'][0]['quantity']=1
 other=record('IMPIANTO',4,quantity=1,encounter='0007');other['payload']['customer']='Nome alternativo';records.append(other)
 result=build_status(records,[link(1),link(1,4,2)],structure='Nome alternativo')
 assert result['status']['closed']==1 and result['Interventi chiusi'][0]['Pezzi chiusi']==2

