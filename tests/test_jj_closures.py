import io
from decimal import Decimal
import pandas as pd
import pytest
from jj_closures import prepare_closure, select_division, decimal, read_all

def workbook(franchise='Trauma'):
    b=io.BytesIO()
    with pd.ExcelWriter(b,engine='openpyxl') as w:
        pd.DataFrame({'Riepilogo':[999]}).to_excel(w,index=False,sheet_name='Pivot')
        pd.DataFrame({
            'Product[P. Bravo Franchise]':[franchise]*2,
            'Product[P. Code]':['413.016S','413.016S'],
            'Order Transactions[O. Customer PO]':['PO-2025','PO-2025'],
            'Order Transactions[O. Invoice Number]':['26123','26123'],
            '[Volumes_Primary]':[2,-1], '[NIS]':[100,-10],
            '[Invoiced_Sales__IS_]':[100,-10],
        }).to_excel(w,index=False,sheet_name='Detail')
    return b.getvalue()

def test_detail_selected_instead_of_first_pivot_and_po_preserved():
    result=prepare_closure(workbook(),'test.xlsx','TRAUMA')
    assert result['sheet']=='Detail'
    assert result['total']=='90'
    assert len(result['rows'])==2
    assert result['rows'][0]['riferimento_cliente']=='PO-2025'
    assert 'numero_ordine' not in result['rows'][0]
    assert result['rows'][1]['quantita']=='-1'

def test_filename_does_not_change_import_identity():
    data=workbook()
    assert prepare_closure(data,'a.xlsx','TRAUMA')['fingerprint']==prepare_closure(data,'renamed.xlsx','TRAUMA')['fingerprint']

@pytest.mark.parametrize('source,selected',[('Trauma','PROTESICA'),('Sconosciuta','TRAUMA')])
def test_wrong_or_unknown_division_rejected(source,selected):
    with pytest.raises(ValueError,match='divisione'):
        prepare_closure(workbook(source),'a.xlsx',selected)

def test_forecasts_and_closures_never_mix_divisions():
    data=pd.DataFrame({'divisione':['TRAUMA','PROTESICA',None,'mista'],'value':[10,100,1000,10000]})
    assert select_division(data,'TRAUMA')['value'].sum()==10
    assert select_division(data,'PROTESICA')['value'].sum()==100
    assert select_division(data.drop(columns='divisione'),'TRAUMA').empty

def test_invalid_money_does_not_silently_become_zero():
    assert decimal('1.200,50 EUR')==Decimal('1200.50')
    with pytest.raises(ValueError): decimal('non leggibile')
    with pytest.raises(ValueError): decimal('Infinity')

def test_detail_export_reads_more_than_postgrest_response_limit():
    from types import SimpleNamespace
    data=[{'id':i,'totale_riga':1} for i in range(2273)]
    class Client:
        def table(self,*a):return self
        def select(self,*a):return self
        def order(self,*a):return self
        def eq(self,*a):return self
        def range(self,start,end):self.bounds=(start,end);return self
        def execute(self):return SimpleNamespace(data=data[self.bounds[0]:self.bounds[1]+1])
    result=read_all(Client(),'righe_chiusura_johnson',{'chiusura_id':1})
    assert len(result)==2273
    assert result['totale_riga'].sum()==2273
