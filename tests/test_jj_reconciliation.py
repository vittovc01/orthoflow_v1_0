import pytest
from jj_reconciliation import prepare_tab,prepare_orders,prepare_month,proposals,residuals,accounts,closing_orders,confirmed_associations

def record(kind,id,quantity=2,**extra):
 line={'key':'line','ref':'413.016S','lot':'L1' if kind=='IMPIANTO' else '', 'quantity':quantity,'cac':'100','customer':'Sapri','po':'PO1','invoice':'F1','date':'2026-10-10','price':'10','total':str(10*quantity)}
 return {'id':id,'kind':kind,'division':'TRAUMA','source_key':str(id),'payload':{'cac':'100','lines':[line],'event_date':'2026-09-01','reference':'cc 1 del 01/09/2026',**extra}}

def test_orders_without_lot_accept_repeated_headers_and_sum_duplicate_rows():
 closing=record('CHIUSURA',1)
 csv='ordine;codice;descrizione;quantità;prezzo unitario;totale\nPO1;Codice prodotto;Descrizione;Quantità;Prezzo unitario;Totale\nPO1;413.016S;vite;1;10,00 EUR;10,00 EUR\nPO1;413.016S;vite;1;10,00 EUR;10,00 EUR\n'
 r=prepare_orders(csv.encode(),'ordini.csv','TRAUMA',[closing])
 assert len(r)==1 and len(r[0]['payload']['lines'])==1
 assert r[0]['payload']['lines'][0]['quantity']==2
 assert r[0]['payload']['lines'][0]['lot']==''
 assert r[0]['payload']['number']=='' and r[0]['payload']['po']=='PO1'
 previous={'id':9,'kind':'ORDINE','division':'TRAUMA',**r[0]}
 with_number=csv.replace('ordine;codice;','Numero ordine J&J;ordine;codice;').replace('PO1;','184000-KO;PO1;')
 assert prepare_orders(with_number.encode(),'n.csv','TRAUMA',[closing,previous])[0]['source_key']==r[0]['source_key']

def test_ambiguous_po_requires_presidio_and_quantity_is_validated():
 a=record('CHIUSURA',1);b=record('CHIUSURA',2);b['payload']['lines'][0]['cac']='200'
 csv='PO cliente;REF;Quantità\nPO1;413.016S;1\n'
 with pytest.raises(ValueError,match='presidio'):prepare_orders(csv.encode(),'x.csv','TRAUMA',[a,b])
 for qty in ['0','-1','1.5','Infinity']:
  with pytest.raises(ValueError):prepare_orders(csv.replace(';1\n',';'+qty+'\n').encode(),'x.csv','TRAUMA',[a])

def test_tab_document_identity_stable_and_asl_not_mapped_globally():
 header='tipo;numero;cliente;articolo;lotto;riferimento;data;quantità;serie;causale\n'
 csv=header+'DDT;1;ASL SALERNO;413.016S;L1;cc 007 del 01/09/2026;02/09/2026;1;T;AVVENUTO IMPIANTO TRAUMA\n'
 r=prepare_tab(csv.encode(),'TAB.csv','TRAUMA')
 assert r[0]['source_key']=='2026|DDT|T|1'
 assert r[0]['payload']['cac']==''
 assert {'6977429','7533619','6977437'}.issubset(accounts([]))
 assert r[0]['payload']['event_date']=='2026-09-01'
 assert r[0]['payload']['document_date']=='2026-09-02'
 assert r[0]['payload']['encounter']=='007'
 updated=prepare_tab(csv.replace(';1;T;',';2;T;').encode(),'renamed.csv','TRAUMA')
 assert updated[0]['source_key']==r[0]['source_key']
 with pytest.raises(ValueError,match='singolo documento'):prepare_tab(csv.encode(),'x.csv','TRAUMA',mapping={'ASL SALERNO':'100'})
 saved={'id':1,'kind':'IMPIANTO','division':'TRAUMA',**r[0]}
 saved['payload']['cac']='100'
 saved['payload']['lines'][0]['cac']='100'
 saved['payload']['event_date']='2026-09-03'
 # An explicit per-document assignment/date correction survives cumulative TAB reloads.
 assert prepare_tab(csv.encode(),'updated.csv','TRAUMA',[saved])[0]['payload']==saved['payload']

def test_no_lot_proposals_cross_month_and_never_auto_choose_ambiguous_implant():
 records=[record('CHIUSURA',1),record('ORDINE',2),record('IMPIANTO',3)]
 result=proposals(records,[])
 assert len(result)==1 and result[0]['Univoco']
 assert 'non disponibile' in result[0]['Metodo']
 records.append(record('IMPIANTO',4))
 assert len(proposals(records,[]))==2 and not any(r['Univoco'] for r in proposals(records,[]))
 records[3]['division']='PROTESICA'
 assert len(proposals(records,[]))==1

def test_residual_quantity_not_assigned_twice_and_pending_revision_excluded():
 records=[record('CHIUSURA',1),record('ORDINE',2),record('IMPIANTO',3)]
 link={**{s+'_id':i for s,i in [('closure',1),('order',2),('implant',3)]},**{s+'_line':'line' for s in ['closure','order','implant']},'quantity':1,'revoked_at':None}
 assert proposals(records,[link])[0]['quantity']==1
 assert all(r['Residuo']==1 for r in residuals(records,[link]))
 records[2]['pending_payload']={'lines':[]}
 assert proposals(records,[link])==[]
 assert residuals(records,[link])[-1]['Stato']=='REVISIONE DA VERIFICARE'

def test_closure_period_not_guessed_from_invoice_date():
 csv='Product[P. Bravo Franchise];Product[P. Code];[Invoiced_Sales__IS_];[Volumes_Primary];Calendar[D. Year];Calendar[D. Month Code];C Account[C. Account Code (CAC)];Order Transactions[O. Customer PO];Order Transactions[O. Invoice Number];Calendar[Date];Order Type[O. Sub Type]\nTrauma;413.016S;10;1;2026;10;100;PO1;F1;30/09/2026;Consignment Sale\n'
 assert prepare_month(csv.encode(),'c.csv','TRAUMA','2026-10-01')[0]['payload']['month']=='2026-10'
 with pytest.raises(ValueError,match='mese'):prepare_month(csv.encode(),'c.csv','TRAUMA','2026-11-01')

def test_complete_composition_does_not_hide_other_clinical_records():
 records=[record('CHIUSURA',1,quantity=1),record('ORDINE',2,quantity=1),record('IMPIANTO',3,quantity=1),record('IMPIANTO',4,quantity=1)]
 for r in records[:3]:r['payload']['lines'].append({**r['payload']['lines'][0],'key':'second','ref':'413.020S'})
 result=proposals(records,[])
 assert len(result)==3
 assert {r['implant_id'] for r in result}=={3,4}
 assert not any(r['Univoco'] for r in result if r['REF']=='413.016S')

def test_closure_order_list_keeps_po_separate_from_supplier_number():
 records=[record('CHIUSURA',1),record('ORDINE',2,po='PO1',number='JJ-123',cac='100')]
 rows=closing_orders(records,1)
 assert rows[0]['PO cliente']=='PO1'
 assert rows[0]['Fattura']=='F1'
 assert rows[0]['Ordini presenti']=='JJ-123'

def test_known_order_can_have_two_invoices_without_dropping_line_identity():
 csv='CAC;PO cliente;Numero ordine J&J;Numero fattura;REF;Quantità\n100;PO1;JJ1;F1;413.016S;1\n100;PO1;JJ1;F2;413.016S;1\n'
 result=prepare_orders(csv.encode(),'o.csv','TRAUMA')
 assert len(result)==1
 assert len(result[0]['payload']['lines'])==2
 assert {l['invoice'] for l in result[0]['payload']['lines']}=={'F1','F2'}
 assert result[0]['payload']['invoice']==''


def test_mixed_order_splits_same_ref_across_cc_only_within_presidio_and_remaining_quantities():
 records=[record('CHIUSURA',1,quantity=3),record('ORDINE',2,quantity=3),
          record('IMPIANTO',3,quantity=2,encounter='001'),record('IMPIANTO',4,quantity=1,encounter='002'),
          record('IMPIANTO',5,quantity=1,encounter='003'),record('IMPIANTO',6,quantity=3,encounter='OTHER')]
 for r in records[:2]:r['payload']['lines'].append({**r['payload']['lines'][0],'key':'B','ref':'413.020S','quantity':1,'total':'10'})
 records[4]['payload']['lines'][0].update(ref='413.020S',key='B')
 records[5]['payload'].update(cac='200');records[5]['payload']['lines'][0]['cac']='200'
 result=proposals(records,[])
 assert {(r['Cartella clinica'],r['REF'],r['quantity']) for r in result}=={('001','413.016S',2),('002','413.016S',1),('003','413.020S',1)}
 assert not any(r['implant_id']==6 for r in result)
 # A prior allocation consumes all three residuals, not the entire clinical record.
 link={k:result[0][k] for k in ('closure_id','closure_line','order_id','order_line','implant_id','implant_line')}
 link.update(quantity=1,revoked_at=None)
 result=proposals(records,[link])
 assert next(r for r in result if r['Cartella clinica']=='001')['quantity']==1
 # The confirmed export preserves which CC supplied each part of the same order.
 links=[]
 for n,r in enumerate(proposals(records,[])):
  links.append({**{k:r[k] for k in ('closure_id','closure_line','order_id','order_line','implant_id','implant_line','quantity')},'id':n,'method':'MANUALE','actor':'reviewer','created_at':'2026-11-02','revoked_at':None})
 exported=confirmed_associations(records,links,1)
 assert {r['Cartella clinica'] for r in exported}=={'001','002','003'}
 assert sum(r['Quantità'] for r in exported)==4
 assert {r['CAC'] for r in exported}=={'100'}
 links[0]['revoked_at']='2026-11-03'
 assert len(confirmed_associations(records,links,1))==2
