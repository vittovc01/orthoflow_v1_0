from io import BytesIO
from zipfile import ZipFile,ZIP_DEFLATED
import xml.etree.ElementTree as ET
import openpyxl
import pytest
from jj_order_template import order_template,structure_catalog
from jj_reconciliation import prepare_orders
from tests.test_jj_reconciliation import record

CUSTOMERS=[{'codice_cliente':'00901','descrizione':'Sapri','citta':'Sapri','provincia':'SA'},
 {'codice_cliente':'00902','descrizione':'Sapri','citta':'Altro comune','provincia':'nan'},
 {'codice_cliente':'00903','descrizione':'Nuova struttura','citta':'nan'}]

def filled_template(content,label):
 """Fill input cells while leaving formulas uncached, as in a downloaded template."""
 ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
 output=BytesIO()
 with ZipFile(BytesIO(content)) as source,ZipFile(output,'w',ZIP_DEFLATED) as target:
  for name in source.namelist():
   data=source.read(name)
   if name=='xl/worksheets/sheet1.xml':
    tree=ET.fromstring(data);row=tree.find(f'.//{{{ns}}}row[@r="2"]')
    for address,value in {'A2':'PO1','B2':'F1','C2':'413.016S','E2':30,'F2':3,'I2':label}.items():
     cell=row.find(f'{{{ns}}}c[@r="{address}"]')
     if cell is None:cell=ET.SubElement(row,f'{{{ns}}}c',{'r':address})
     for child in list(cell):cell.remove(child)
     if isinstance(value,str):
      cell.set('t','inlineStr');ET.SubElement(ET.SubElement(cell,f'{{{ns}}}is'),f'{{{ns}}}t').text=value
     else:
      cell.attrib.pop('t',None);ET.SubElement(cell,f'{{{ns}}}v').text=str(value)
    data=ET.tostring(tree)
   target.writestr(name,data)
 return output.getvalue()

def test_catalog_keeps_all_codes_disambiguates_names_and_cleans_nan():
 catalog=structure_catalog(CUSTOMERS)
 assert len(catalog)==3 and len({r['Scelta struttura'] for r in catalog})==3
 assert {r['Codice struttura'] for r in catalog}=={'00901','00902','00903'}
 assert 'nan' not in str(catalog)
 assert all(not r['CAC J&J'] for r in catalog)

def test_template_has_current_full_catalog_dropdown_and_automatic_codes():
 content=order_template(CUSTOMERS,[record('CHIUSURA',1)],'PROTESICA')
 wb=openpyxl.load_workbook(BytesIO(content),data_only=False)
 assert wb.sheetnames==['Ordini','Anagrafica strutture','Impostazioni']
 assert wb['Anagrafica strutture'].max_row==4
 assert wb['Impostazioni']['B2'].value=='PROTESICA'
 assert 'E2/F2' in wb['Ordini']['G2'].value
 assert 'VLOOKUP(I2' in wb['Ordini']['J2'].value and ',3,FALSE)' in wb['Ordini']['J2'].value
 assert ',6,FALSE)' in wb['Ordini']['K2'].value
 assert 'I2:I1001' in str(wb['Ordini'].data_validations)
 assert wb['Anagrafica strutture']['C2'].data_type=='s'
 with pytest.raises(ValueError,match='vuota'):order_template([],[],'TRAUMA')

def test_import_recovers_uncached_lookup_and_total_formulas_without_confusing_codes():
 customers=[CUSTOMERS[0],CUSTOMERS[2]]
 records=[record('CHIUSURA',1)];catalog=structure_catalog(customers,records)
 label=next(r['Scelta struttura'] for r in catalog if r['Codice struttura']=='00901')
 content=filled_template(order_template(customers,records,'TRAUMA'),label)
 result=prepare_orders(content,'o.xlsx','TRAUMA',records,customers)
 payload=result[0]['payload'];line=payload['lines'][0]
 assert payload['customer_code']=='00901' and payload['customer']=='Sapri' and payload['cac']=='100'
 assert line['customer_code']=='00901' and line['quantity']==3 and float(line['price'])==10
 with pytest.raises(ValueError,match='divisione diversa'):prepare_orders(content,'o.xlsx','PROTESICA',records,CUSTOMERS)

def test_identical_names_do_not_inherit_each_others_cac():
 catalog=structure_catalog(CUSTOMERS,[record('CHIUSURA',1)])
 assert all(not r['CAC J&J'] for r in catalog)
 explicit=record('IMPIANTO',3);explicit['payload']['customer_code']='00901'
 catalog=structure_catalog(CUSTOMERS,[explicit])
 assert next(r for r in catalog if r['Codice struttura']=='00901')['CAC J&J']=='100'
 assert not next(r for r in catalog if r['Codice struttura']=='00902')['CAC J&J']

def test_internal_code_cannot_be_used_as_cac_and_wrong_structure_is_rejected():
 csv='PO cliente;REF;Quantità;Presidio;Codice struttura;CAC\nPO1;413.016S;1;Sapri;00901;00901\n'
 with pytest.raises(ValueError,match='non è il CAC'):prepare_orders(csv.encode(),'o.csv','TRAUMA',[],CUSTOMERS)
 with pytest.raises(ValueError,match='discordanti'):prepare_orders(csv.replace('Sapri;','Altra clinica;').encode(),'o.csv','TRAUMA',[],CUSTOMERS)

def test_cumulative_orders_keep_stable_identity_and_do_not_accumulate_previous_quantities():
 csv='CAC;PO cliente;REF;Quantità;Totale riga\n100;PO1;413.016S;2;20\n'
 first=prepare_orders(csv.encode(),'ottobre.csv','TRAUMA')
 old={'id':2,'kind':'ORDINE','division':'TRAUMA',**first[0]}
 updated=csv+'100;PO1;413.020S;1;12\n100;PO2;413.030S;1;15\n'
 result=prepare_orders(updated.encode(),'novembre.csv','TRAUMA',[old])
 assert len(result)==2 and result[0]['source_key']==old['source_key']
 assert sum(l['quantity'] for l in result[0]['payload']['lines'])==3
 saved=[{'id':i+2,'kind':'ORDINE','division':'TRAUMA',**r} for i,r in enumerate(result)]
 assert prepare_orders(updated.encode(),'ancora.csv','TRAUMA',saved)==result

