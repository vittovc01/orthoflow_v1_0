from datetime import date
from types import SimpleNamespace
from pathlib import Path
import pytest
from shelf_scanning import parse_product,find_product_mapping,shelf_url,shelf_target

GTIN='07611819425248'
def payload(lot):return '01'+GTIN+'17'+'351200'+'10'+lot

class Query:
    def __init__(self,db,table):self.db,self.table,self.filters=db,table,{};self.predicates=[]
    def select(self,*a,**k):return self
    def eq(self,k,v):self.filters[k]=v;return self
    def in_(self,k,values):self.predicates.append(lambda r:r.get(k) in values);return self
    def gt(self,k,value):self.predicates.append(lambda r:r.get(k,0)>value);return self
    def execute(self):
        return SimpleNamespace(data=[r for r in self.db.rows.get(self.table,[]) if all(r.get(k)==v for k,v in self.filters.items()) and all(p(r) for p in self.predicates)])
    def __getattr__(self,name):
        if name in {'insert','update','upsert','delete'}:raise AssertionError('No stock writes in scan tests')
        return lambda *a,**k:self
class Backend:
    def __init__(self,rows):self.rows=rows
    def table(self,name):return Query(self,name)


def test_compact_gs1_reads_new_lot_and_month_end_without_guessing():
    a,b=parse_product(payload('LOT1')),parse_product(']d2'+payload('LOT2'))
    assert a['gtin']==b['gtin']==GTIN
    assert a['lotto']=='LOT1' and b['lotto']=='LOT2'
    assert b['scadenza']==date(2035,12,31)
    assert parse_product('(01)'+GTIN+'(17)351231(10)LOT2')['lotto']=='LOT2'
    assert parse_product('01'+GTIN+'10LOT17123456')['scadenza'] is None


def test_learned_ref_is_reused_across_lots():
    db=Backend({'codici_prodotto_scan':[{'codice_scansionato':payload('LOT1'),'gtin':GTIN,
                                       'codice_articolo':'04.211.016S','attivo':True}]})
    scanned=parse_product(payload('LOT2'))
    assert find_product_mapping(db,scanned)['codice_articolo']=='04.211.016S'
    assert scanned['lotto']=='LOT2'


def test_catalogue_preferred_and_ambiguous_learned_mapping_not_chosen():
    db=Backend({'articoli_gtin':[{'gtin':GTIN,'ref':'CAT-REF'}],
                'codici_prodotto_scan':[{'gtin':GTIN,'codice_articolo':'OLD','attivo':True}]})
    assert find_product_mapping(db,parse_product(payload('L')))['codice_articolo']=='CAT-REF'
    db.rows.pop('articoli_gtin')
    db.rows['codici_prodotto_scan'].append({'gtin':GTIN,'codice_articolo':'OTHER','attivo':True})
    assert 'mapping_error' in find_product_mapping(db,parse_product(payload('L')))


def test_gtin_only_cannot_supply_a_lot():
    result=parse_product(GTIN)
    assert result['gtin']==GTIN and not result['lotto'] and result['scadenza'] is None


def test_phone_link_roundtrip_and_legacy_identifiers():
    link=shelf_url('https://example.org/','mag1','a','02')
    assert link.startswith('https://example.org/?shelf=')
    assert shelf_target(link)==shelf_target('OFWMS:SHELF:MAG1|A|02')==('MAG1','A','02')
    assert shelf_target(('MAG1','A','02'))==('MAG1','A','02')
    assert shelf_target('nonsense') is None
    with pytest.raises(ValueError):shelf_url('javascript:alert(1)','A','B','C')


def test_shelf_link_survives_login_and_selects_target_without_writes(monkeypatch):
    import streamlit as st
    import supabase
    from streamlit.testing.v1 import AppTest
    db=Backend({'v_wms_scaffali':[{'codice_magazzino':'MAG1','corsia':'A','scaffale':'01'},
                                  {'codice_magazzino':'MAG1','corsia':'A','scaffale':'02'}]})
    st.cache_resource.clear();st.cache_data.clear()
    monkeypatch.setattr(supabase,'create_client',lambda *a,**k:db)
    at=AppTest.from_file(Path(__file__).resolve().parents[1]/'app.py',default_timeout=30)
    at.secrets['SUPABASE_URL']='http://localhost:1';at.secrets['SUPABASE_SERVICE_KEY']='test'
    at.query_params['shelf']='OFWMS:SHELF:MAG1|A|02'
    at.run()
    assert not at.exception and any('Accedi' in b.label for b in at.button)
    assert at.session_state['wms_shelf_target']==('MAG1','A','02')
    at.session_state['user']='test';at.session_state['ruolo']='Admin';at.session_state['permessi']=[]
    at.run()
    assert not at.exception
    assert at.session_state['managed_shelf_choice']==1
    assert any('Gestione Scaffale' in t.value for t in at.title)
    st.cache_resource.clear();st.cache_data.clear()


def test_second_product_scan_refreshes_form_ref_and_lot(monkeypatch):
    import streamlit as st
    import supabase
    from streamlit.testing.v1 import AppTest
    db=Backend({'v_wms_scaffali':[{'codice_magazzino':'MAG1','corsia':'A','scaffale':'01'}],
                'codici_prodotto_scan':[{'gtin':GTIN,'codice_articolo':'04.211.016S','attivo':True}]})
    st.cache_resource.clear();st.cache_data.clear()
    monkeypatch.setattr(supabase,'create_client',lambda *a,**k:db)
    at=AppTest.from_file(Path(__file__).resolve().parents[1]/'pages/03_Gestione_Scaffale.py',default_timeout=30)
    at.secrets['SUPABASE_URL']='http://localhost:1';at.secrets['SUPABASE_SERVICE_KEY']='test'
    at.session_state['user']='test';at.session_state['ruolo']='Admin';at.session_state['permessi']=[]
    at.run()
    def field(label):return next(x for x in at.text_input if x.label==label)
    field('Oppure inserisci/incolla il codice letto').set_value(payload('LOT1')).run()
    assert not at.exception
    assert field('Codice articolo Johnson').value=='04.211.016S' and field('Lotto').value=='LOT1'
    field('Oppure inserisci/incolla il codice letto').set_value(payload('LOT2')).run()
    assert not at.exception
    assert field('Codice articolo Johnson').value=='04.211.016S' and field('Lotto').value=='LOT2'
    assert next(x for x in at.date_input if x.label=='Scadenza').value==date(2035,12,31)
    next(x for x in at.button if x.label=='Nuova scansione prodotto').click().run()
    assert not at.exception and field('Oppure inserisci/incolla il codice letto').value==''
    assert field('Lotto').value=='' and at.session_state['shelf_scan_revision']==1
    st.cache_resource.clear();st.cache_data.clear()


def test_live_shelf_replaces_withdrawn_lot_and_discovers_new_positions(monkeypatch):
    import streamlit as st
    import supabase
    from streamlit.testing.v1 import AppTest
    def location(id, level, position):
        return dict(id=id,codice_magazzino='MAG1',corsia='A',scaffale='01',
                    ripiano=level,posizione=position,codice_ubicazione=f'MAG1-A-01-{level}-{position}',attiva=True)
    db=Backend({'v_wms_scaffali':[{'codice_magazzino':'MAG1','corsia':'A','scaffale':'01'}],
                'ubicazioni_magazzino':[location(1,'A','01'),location(2,'A','02')],
                'giacenze_ubicazioni':[
                    dict(ubicazione_id=1,codice='REF1',lotto='OLD',scadenza='2030-01-01',quantita=1),
                    dict(ubicazione_id=999,codice='OTHER-SHELF',lotto='OUTSIDE',quantita=5)]})
    link=shelf_url('https://example.org','MAG1','A','01')
    st.cache_resource.clear();st.cache_data.clear()
    monkeypatch.setattr(supabase,'create_client',lambda *a,**k:db)
    at=AppTest.from_file(Path(__file__).resolve().parents[1]/'pages/03_Gestione_Scaffale.py',default_timeout=30)
    at.secrets['SUPABASE_URL']='http://localhost:1';at.secrets['SUPABASE_SERVICE_KEY']='test'
    at.session_state['user']='test';at.session_state['ruolo']='Admin';at.session_state['permessi']=[]
    at.run()
    assert not at.exception
    assert len(at.dataframe)==1 and at.dataframe[0].value['lotto'].tolist()==['OLD']
    assert any(x.value=='Postazione vuota' for x in at.caption)
    # Simulate movements recorded by another operator, including a new position.
    db.rows['giacenze_ubicazioni'][0]['quantita']=0
    db.rows['ubicazioni_magazzino'].append(location(3,'B','03'))
    db.rows['giacenze_ubicazioni'].append(dict(ubicazione_id=3,codice='REF1',lotto='NEW',scadenza='2032-02-01',quantita=2))
    next(b for b in at.button if b.label=='Aggiorna elenco scaffale').click().run()
    assert not at.exception
    assert len(at.dataframe)==1
    assert at.dataframe[0].value['lotto'].tolist()==['NEW']
    assert at.dataframe[0].value['quantita'].tolist()==[2]
    labels=[x.value for x in at.markdown]
    assert '### Ripiano B' in labels and '**Postazione 03**' in labels
    assert shelf_url('https://example.org','MAG1','A','01')==link
    st.cache_resource.clear();st.cache_data.clear()
