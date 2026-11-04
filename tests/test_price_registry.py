from copy import deepcopy
from datetime import date
from pathlib import Path
import pytest
import streamlit as st
import supabase
from streamlit.testing.v1 import AppTest
from price_registry import catalog_rows,registry_presidi
from tab_verified_prices import daily_period
from tests.test_tab_verified_prices import PricesBackend,verified,report
from tests.test_tab_price_anomalies import page

ROOT=Path(__file__).resolve().parents[1]


def cats(b):return [b.data[k] for k in ('clienti','offerte_header','offerte_clienti','offerte_prezzi')]


def test_registry_combines_original_offers_and_manual_prices_without_changing_shared_offers():
 b=PricesBackend();before=deepcopy(cats(b))
 effective,offers,manual=catalog_rows(cats(b),[verified()], '00901','TRAUMA','100',date(2026,9,1))
 assert effective[0]['Prezzo applicato']==10 and effective[0]['Fonte']=='Manuale'
 assert offers[0]['Prezzo offerta']=='8' and manual[0]['prezzo']=='10'
 assert cats(b)==before
 other,_,_=catalog_rows(cats(b),[verified()], '00901','TRAUMA','200',date(2026,9,1))
 assert other[0]['Prezzo applicato']==8 and other[0]['Fonte']=='Offerta'
 expired,_,_=catalog_rows(cats(b),[verified()], '00901','TRAUMA','100',date(2027,9,1))
 assert expired[0]['Prezzo applicato'] is None


def test_registry_includes_offers_without_implants_and_manual_only_refs():
 b=PricesBackend();manual=[verified(ref='MANUALONLY',prezzo='25')]
 rows,_,_=catalog_rows(cats(b),manual,'00901','TRAUMA','100',date(2026,9,1))
 assert {r['REF'] for r in rows}=={'413.016S','MANUALONLY'}
 assert next(r for r in rows if r['REF']=='MANUALONLY')['Prezzo applicato']==25
 assert registry_presidi([],cats(b)[0],'00901','TRAUMA')=={'':'Struttura'}


def test_daily_price_form_has_no_dates_or_reference_and_preserves_configured_period(monkeypatch):
 b=PricesBackend();b.data['offerte_prezzi']=[]
 at=page(monkeypatch,b).run();assert not at.exception
 assert not at.date_input
 assert not any(x.label=='Riferimento verifica prezzo' for x in at.text_input)
 next(x for x in at.number_input if x.label=='Prezzo unitario verificato (€)').set_value(10)
 next(x for x in at.button if x.label=='Salva prezzo e ricalcola anomalie').click().run()
 assert not at.exception and b.writes[0][1]['p_nota'] and b.writes[0][1]['p_dal']=='2026-01-01'
 assert next(x for x in at.metric if x.label=='Segnalazioni TAB').value=='0'
 item={'Date':{'2026-09-01'},'Codice struttura':'00901','CAC':'100','Divisione':'TRAUMA','REF':'413.016S'}
 assert daily_period(item,[verified(dal='2026-04-01',al='2026-10-31')])==(date(2026,4,1),date(2026,10,31))
 with pytest.raises(ValueError):daily_period(item,[verified(dal='2026-01-01',al='2026-06-30')])
 st.cache_resource.clear();st.cache_data.clear()


def registry_app(monkeypatch,b):
 st.cache_resource.clear();st.cache_data.clear()
 monkeypatch.setattr(supabase,'create_client',lambda *a,**kw:b)
 at=AppTest.from_file(str(ROOT/'app.py'),default_timeout=30)
 at.secrets['SUPABASE_URL']='http://127.0.0.1:1';at.secrets['SUPABASE_SERVICE_KEY']='fake'
 at.session_state['user']='test';at.session_state['ruolo']='Admin';at.session_state['permessi']=['DIREZIONE']
 at.run();at.switch_page('pages/18_Anagrafica_Prezzi.py').run()
 return at


def test_registry_navigation_and_manual_edit_update_management_without_modifying_offer(monkeypatch):
 b=PricesBackend();before=deepcopy(b.data['offerte_prezzi'])
 at=registry_app(monkeypatch,b);assert not at.exception
 assert any(x.value=='Anagrafica prezzi' for x in at.title)
 next(x for x in at.date_input if x.label=='Consulta prezzi alla data').set_value(date(2026,9,1)).run()
 next(x for x in at.selectbox if x.label=='REF anagrafica').select('413.016S').run()
 assert not at.exception
 assert next(x for x in at.number_input if x.label=='Prezzo unitario anagrafica (€)').value==8
 next(x for x in at.number_input if x.label=='Prezzo unitario anagrafica (€)').set_value(10)
 next(x for x in at.button if x.label=='Salva prezzo in anagrafica').click().run()
 assert not at.exception and len(b.writes)==1
 assert b.data['offerte_prezzi']==before
 assert b.writes[0][1]['p_nota']=='Modifica manuale da Anagrafica prezzi'
 assert report(b,b.data['tab_prezzi_verificati'])['Prezzi da verificare']==[]
 assert any('Prezzo salvato' in x.value for x in at.success)
 st.cache_resource.clear();st.cache_data.clear()


@pytest.mark.parametrize('user,permissions',[('',[]),('test',['AGENTE']),('test',['LOGISTICA'])])
def test_registry_is_blocked_before_data_access(monkeypatch,user,permissions):
 def forbidden(*a,**kw):raise AssertionError('Unauthorized data access')
 monkeypatch.setattr(supabase,'create_client',forbidden)
 at=AppTest.from_file(str(ROOT/'pages/18_Anagrafica_Prezzi.py'))
 at.session_state['user']=user;at.session_state['ruolo']='Agente';at.session_state['permessi']=permissions
 at.run();assert not at.exception and any('non autorizzato' in x.value for x in at.error)
