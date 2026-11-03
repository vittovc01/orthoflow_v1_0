from copy import deepcopy
from datetime import date
from types import SimpleNamespace
import pytest
import streamlit as st
from tab_verified_prices import add_verified_prices,save_verified_price,worklist
from tab_management import management_report
from jj_intervention_status import build_status
from tests.test_tab_price_anomalies import Backend,page,model


def verified(price='10',**overrides):
 return {'id':1,'codice_cliente':'00901','cac':'100','linea':'TRAUMA','ref':'413.016S','prezzo':price,'dal':'2026-01-01','al':'2026-12-31',**overrides}


def report(backend,rows):
 cats=[deepcopy(backend.data[k]) for k in ('clienti','offerte_header','offerte_clienti','offerte_prezzi')]
 return management_report(backend.data['jj_recon_records'],backend.data['jj_recon_links'],*add_verified_prices(cats,rows),build_status)


def test_verified_price_recalculates_all_same_clinic_ref_lots_without_touching_sources_or_offers():
 b=Backend();before=deepcopy(b.data);source=b.data['jj_recon_records'][2];other=deepcopy(source);other['id']=9;other['source_key']='another';other['payload']['encounter']='NEW';other['payload']['lines'][0]['lot']='OTHER'
 b.data['jj_recon_records'].append(other)
 result=report(b,[verified()])
 assert {r['Prezzo offerta'] for r in result['Prodotti TAB']}=={10}
 assert not result['Prezzi da verificare']
 assert b.data['offerte_prezzi']==before['offerte_prezzi'] and not b.writes
 # Invoice discrepancies do not disappear just because a manual price was entered.
 assert any(r['Esito']=='FATTURA DIVERSA DALL’OFFERTA' for r in report(b,[verified('11')])['Prezzi da verificare'])


@pytest.mark.parametrize('changes',[{'cac':'200'},{'codice_cliente':'OTHER'},{'linea':'PROTESICA'},{'dal':'2027-01-01','al':'2027-12-31'},{'ref':'OTHER'}])
def test_verified_price_does_not_cross_presidio_customer_division_ref_or_dates(changes):
 b=Backend();assert report(b,[verified(**changes)])['Prodotti TAB'][0]['Prezzo offerta']==8


def test_verified_zero_is_known_price_and_missing_dates_are_not_valued():
 b=Backend();assert report(b,[verified('0')])['Prodotti TAB'][0]['Prezzo offerta']==0
 b.data['jj_recon_records'][2]['payload']['event_date']=''
 assert report(b,[verified()])['Prodotti TAB'][0]['Prezzo offerta'] is None


class PricesBackend(Backend):
 def rpc(self,name,args):
  if name!='tab_salva_prezzo_verificato':return super().rpc(name,args)
  def execute():
   self.writes.append((name,args));self.data['tab_prezzi_verificati']=[verified(args['p_prezzo'],codice_cliente=args['p_cliente'],cac=args['p_cac'],linea=args['p_linea'],ref=args['p_ref'],dal=args['p_dal'],al=args['p_al'])]
   return SimpleNamespace(data={'id':1})
  return SimpleNamespace(execute=execute)


def test_direct_save_form_closes_all_matching_checks_and_keeps_structure_filter(monkeypatch):
 b=PricesBackend();b.data['offerte_prezzi']=[]
 at=page(monkeypatch,b).run();assert not at.exception
 next(x for x in at.selectbox if x.label=='Struttura anomalie TAB').select('Sapri').run()
 next(x for x in at.number_input if x.label=='Prezzo unitario verificato (€)').set_value(10)
 next(x for x in at.text_input if x.label=='Riferimento verifica prezzo').set_value('Customer ordine PO1')
 next(x for x in at.button if x.label=='Salva prezzo e ricalcola anomalie').click().run()
 assert not at.exception and len(b.writes)==1
 assert b.writes[0][1]['p_nota']=='Customer ordine PO1' and b.writes[0][1]['p_utente']=='test'
 assert next(x for x in at.selectbox if x.label=='Struttura anomalie TAB').value=='Sapri'
 assert next(x for x in at.metric if x.label=='Segnalazioni TAB').value=='0'
 assert any('Prezzo salvato' in x.value for x in at.success)
 st.cache_resource.clear();st.cache_data.clear()


def test_invalid_blank_price_or_note_never_calls_server(monkeypatch):
 b=PricesBackend();b.data['offerte_prezzi']=[];at=page(monkeypatch,b).run()
 next(x for x in at.button if x.label=='Salva prezzo e ricalcola anomalie').click().run()
 assert not at.exception and not b.writes and at.error
 st.cache_resource.clear();st.cache_data.clear()


def test_structure_next_search_sort_and_grouped_ref_workflow(monkeypatch):
 b=Backend();b.data['offerte_prezzi']=[]
 r=deepcopy(b.data['jj_recon_records'][2]);r['id']=99;r['source_key']='new';r['payload'].update(customer='Z Clinic',cac='200',customer_code='00902');b.data['jj_recon_records'].append(r)
 b.data['clienti'].append({'codice_cliente':'00902','descrizione':'Z Clinic'})
 at=page(monkeypatch,b).run()
 next(x for x in at.selectbox if x.label=='Struttura anomalie TAB').select('Sapri').run()
 next(x for x in at.text_input if x.label=='Cerca REF o descrizione').set_value('NOTTHERE').run()
 assert next(x for x in at.metric if x.label=='Segnalazioni TAB').value=='0'
 next(x for x in at.button if x.label=='Struttura successiva con anomalie').click().run()
 assert not at.exception
 assert next(x for x in at.selectbox if x.label=='Struttura anomalie TAB').value=='Z Clinic'
 assert next(x for x in at.text_input if x.label=='Cerca REF o descrizione').value==''
 assert next(x for x in at.metric if x.label=='Segnalazioni TAB').value=='1'
 next(x for x in at.selectbox if x.label=='Ordina anomalie per').select('REF e struttura').run()
 assert not at.exception and not b.writes
 st.cache_resource.clear();st.cache_data.clear()


def test_validation_blocks_nonfinite_negative_and_unknown_scope():
 b=PricesBackend();scope={'Codice struttura':'00901','CAC':'100','Divisione':'TRAUMA','REF':'413.016S'}
 for value in [None,'nan','inf','-1','0']:
  with pytest.raises(ValueError):save_verified_price(b,scope,value,date(2026,1,1),date(2026,12,31),'user','Customer')
 with pytest.raises(ValueError):save_verified_price(b,{**scope,'Codice struttura':''},10,date(2026,1,1),date(2026,12,31),'user','Customer')
 assert b.writes==[]


def test_save_keeps_remaining_refs_of_same_clinic_ready(monkeypatch):
 b=PricesBackend();b.data['offerte_prezzi']=[]
 product=deepcopy(b.data['jj_recon_records'][2]['payload']['lines'][0]);product.update(key='R2',ref='Z2',lot='L2')
 b.data['jj_recon_records'][2]['payload']['lines'].append(product)
 at=page(monkeypatch,b).run()
 next(x for x in at.selectbox if x.label=='Struttura anomalie TAB').select('Sapri').run()
 next(x for x in at.number_input if x.label=='Prezzo unitario verificato (€)').set_value(10)
 next(x for x in at.text_input if x.label=='Riferimento verifica prezzo').set_value('Customer')
 next(x for x in at.button if x.label=='Salva prezzo e ricalcola anomalie').click().run()
 assert not at.exception
 assert next(x for x in at.selectbox if x.label=='Struttura anomalie TAB').value=='Sapri'
 ref=next(x for x in at.selectbox if x.label=='REF da completare')
 assert len(ref.options)==1 and 'Z2' in ref.options[0]
 assert next(x for x in at.number_input if x.label=='Prezzo unitario verificato (€)').value is None
 st.cache_resource.clear();st.cache_data.clear()


def test_erp_structure_without_customer_cac_can_be_priced_but_not_mixed_with_known_presidio():
 b=Backend();b.data['jj_recon_records'][2]['payload']['cac']=''
 b.data['jj_recon_links']=[]
 assert report(b,[verified(cac='')])['Prodotti TAB'][0]['Prezzo offerta']==10
 assert report(b,[verified(cac='100')])['Prodotti TAB'][0]['Prezzo offerta']==8
 scope={'Codice struttura':'00901','CAC':'','Divisione':'PROTESICA','REF':'R1'}
 backend=PricesBackend();save_verified_price(backend,scope,10,date(2026,1,1),date(2026,12,31),'user','Customer')
 assert backend.writes[0][1]['p_cac']==''
