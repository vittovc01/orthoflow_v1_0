"""Destination safety and request counts, without real stock writes."""
from types import SimpleNamespace
import ast
from pathlib import Path
from functools import lru_cache

import pytest
from scarico_workflow import reset_destination, destination_errors, stock_snapshot, stock_quantities
from ocr_repository import load_gtin_catalog


def test_new_document_clears_both_prior_choices():
    state = dict(scarico_destination_client={'codice_cliente':'OLD'}, scarico_price_line='TRAUMA',
                 scarico_missing_prices=[1], scarico_stock_errors=[2], unrelated='keep')
    reset_destination(state)
    assert state == dict(scarico_destination_client=None, scarico_price_line=None, unrelated='keep')


@pytest.mark.parametrize('client,line,count', [
    ({},None,2), ({'codice_cliente':'A'},None,1), ({},'TRAUMA',1),
    ({'codice_cliente':'A'},'OTHER',1), ({'descrizione':'A'},'TRAUMA',1),
    ({'codice_cliente':'A'},'PROTESICA',0),
])
def test_destination_guard(client,line,count):
    assert len(destination_errors(client,line)) == count


class Backend:
    def __init__(self, rows, cap=500):
        self.rows=rows;self.cap=cap;self.calls=[];self.filters=[];self.offset=0
    def table(self,name):self.name=name;return self
    def select(self,cols):return self
    def eq(self,*args):return self
    def in_(self,column,values):self.filters.append((column,list(values)));return self
    def order(self,*args):return self
    def range(self,start,end):self.offset=start;return self
    def execute(self):
        self.calls.append(self.name)
        return SimpleNamespace(data=self.rows[self.offset:self.offset+self.cap])


def test_one_snapshot_reused_for_sixteen_codes_and_normalized_stock():
    rows=[dict(codice=f'TEST-{i}',lotto='LOT',quantita=1,scadenza='2035-01-01') for i in range(16)]
    db=Backend(rows)
    snapshot=stock_snapshot(db,'MAG1')
    quantities=stock_quantities(snapshot)
    assert [quantities[(f'TEST{i}','LOT')] for i in range(16)] == [1]*16
    assert len(db.calls)==2  # one data page + end check; no per-row request


def test_capped_pages_are_not_silently_truncated():
    db=Backend([dict(codice='TEST',lotto=None,quantita=q) for q in [1,2,3]],cap=2)
    assert stock_quantities(stock_snapshot(db,'MAG1')) == {('TEST',''):6}
    assert len(db.calls)==3


def test_catalogue_only_requests_detected_gtins_and_handles_capped_pages():
    db=Backend([{'gtin':'G1','ref':'R1'},{'gtin':'G2','ref':'R2'},{'gtin':'G3','ref':'R3'}],cap=2)
    assert load_gtin_catalog(db,gtins=['G1','G2','G3']) == {'G1':'R1','G2':'R2','G3':'R3'}
    assert all(values==['G1','G2','G3'] for _,values in db.filters)
    assert load_gtin_catalog(db,gtins=[None,'','nan']) == {}
    assert len(db.calls)==3


def test_new_analysis_resets_destination_before_replacing_review():
    tree=ast.parse(Path('pages/_05_Scarico_Sala_AI_impl.py').read_text())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run_ai')
    source=ast.unparse(fn)
    assert source.index('reset_destination(st.session_state)') < source.index("st.session_state['scarico_ai_rows'] =")


def test_offer_headers_are_loaded_in_one_request_preserving_priority():
    tree=ast.parse(Path('pages/_05_Scarico_Sala_AI_impl.py').read_text())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='offer_ids_for')
    class Offers(Backend):
        def execute(self):
            self.calls.append(self.name)
            return SimpleNamespace(data=[{'offerta_id':i} for i in range(16)] if self.name=='offerte_clienti'
                else [{'id':i,'linea':'TRAUMA' if i%2==0 else 'PROTESICA'} for i in reversed(range(16))])
    db=Offers([])
    ns=dict(sb=lambda:db,clean=lambda v:str(v or '').strip(),lru_cache=lru_cache)
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'offers','exec'),ns)
    assert ns['offer_ids_for']('A','TRAUMA') == list(range(0,16,2))
    assert db.calls == ['offerte_clienti','offerte_header']


def test_server_guard_rejects_a_forged_submit_before_any_write():
    tree=ast.parse(Path('pages/_05_Scarico_Sala_AI_impl.py').read_text())
    submit=next(n for n in tree.body if isinstance(n,ast.If) and ast.unparse(n.test)=='confirm or archive_review')
    errors=[]
    class Stop(Exception):pass
    def stop():raise Stop()
    ns=dict(confirm=True,selected_client={},line=None,destination_errors=destination_errors,
            st=SimpleNamespace(error=errors.append,stop=stop))
    with pytest.raises(Stop):
        exec(compile(ast.Module(body=[submit.body[0]],type_ignores=[]),'guard','exec'),ns)
    assert len(errors)==2 and 'struttura' in errors[0] and 'linea' in errors[1]
