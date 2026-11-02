import pandas as pd
import streamlit as st
from supabase import create_client
from orthoflow_branding import configure_page
from jj_closures import read_all
from jj_intervention_status import build_status
from jj_report_runtime import current_reports

configure_page(page_title='Stato interventi · P.M. Medical',page_icon='📊',layout='wide')
if not st.session_state.get('user'):st.switch_page('pages/99_Login.py');st.stop()
permissions=set(st.session_state.get('permessi',[]) or [])
if str(st.session_state.get('ruolo',''))!='Admin' and not {'DIREZIONE','AMMINISTRAZIONE'}&permissions:
 st.error('Accesso non autorizzato.');st.stop()

@st.cache_resource
def status_backend():
 key=st.secrets.get('SUPABASE_SERVICE_KEY')
 if not key:raise RuntimeError('Connessione server del modulo chiusure non configurata')
 return create_client(str(st.secrets['SUPABASE_URL']).rstrip('/'),str(key))

@st.cache_data(ttl=30,max_entries=2)
def status_data():
 client=status_backend()
 return read_all(client,'jj_recon_records').to_dict('records'),read_all(client,'jj_recon_links').to_dict('records')

@st.cache_data(ttl=30,max_entries=6)
def status_excel(report):
 return current_reports().excel_report(report)

st.title('Stato interventi')
st.caption('Interventi dai TAB caricati, associati a ordini e fatture di tutti i mesi. I dati non riscontrati restano da verificare.')
if st.button('Aggiorna dati',type='secondary'):
 status_data.clear();status_excel.clear()
try:records,links=status_data()
except Exception:
 st.error('Impossibile leggere i dati. Verificare la connessione server del modulo chiusure.');st.stop()
division=st.radio('Divisione',['Tutte','TRAUMA','PROTESICA'],horizontal=True,key='status_division')
scope=[r for r in records if division=='Tutte' or r['division']==division]
implants=[r for r in scope if r['kind']=='IMPIANTO']
cols=st.columns(2)
structure=cols[0].selectbox('Struttura',['Tutte']+sorted({r['payload'].get('customer') or r['payload'].get('cac') or 'Presidio da assegnare' for r in implants}),key='status_structure_'+division)
years=sorted({str(r['payload'].get('event_date'))[:4] for r in implants if r['payload'].get('event_date')},reverse=True)
year=cols[1].selectbox('Anno intervento',['Tutti']+years,key='status_year_'+division)
report=build_status(records,links,None if division=='Tutte' else division,None if structure=='Tutte' else structure,None if year=='Tutti' else year)
state=report['status']
for col,label,value in zip(st.columns(4),('Interventi chiusi','Da chiudere / verificare','Pezzi da chiudere','Differenze prezzo'),(state['closed'],state['open'],state['remaining_quantity'],state['price_differences'])):
 col.metric(label,value)
st.caption('Report generato il '+state['read_at']+'. Premi Aggiorna dati per includere le ultime importazioni prima di scaricare.')
if state['price_missing']:st.warning(f"{state['price_missing']} confronti prezzo non disponibili: controllare distinte mancanti o prezzi vuoti.")
if not implants:st.info('Nessun intervento TAB caricato per questa divisione. Le fatture e gli ordini non associati restano disponibili nel report e nel dettaglio documenti.')
exportable={k:v for k,v in report.items() if k!='status'}
st.download_button('Scarica Excel aggiornato',status_excel(exportable),'Stato_Interventi_'+division+'_'+state['read_at'][:10]+'.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',type='primary')
closed_tab,open_tab,price_tab=st.tabs(['Chiusi con ordine e fattura','Da chiudere','Prezzi da verificare'])
with closed_tab:
 if report['Interventi chiusi']:st.dataframe(pd.DataFrame(report['Interventi chiusi']),hide_index=True,use_container_width=True)
 else:st.info('Nessun intervento completamente associato a ordine e fattura nei filtri selezionati.')
with open_tab:
 if report['Interventi da chiudere']:st.dataframe(pd.DataFrame(report['Interventi da chiudere']),hide_index=True,use_container_width=True)
 else:st.success('Nessun intervento da chiudere o verificare nei filtri selezionati.')
with price_tab:
 st.caption('Confronto del prezzo della distinta ordine con la chiusura ufficiale. Le offerte commerciali non rientrano in questo confronto.')
 if report['Prezzi da verificare']:st.dataframe(pd.DataFrame(report['Prezzi da verificare']),hide_index=True,use_container_width=True)
 else:st.caption('Nessuno scostamento rilevato nei confronti disponibili.')
with st.expander('Dettaglio prodotti, collegamenti e documenti non associati'):
 for name in ('Dettaglio prodotti','Ordini e fatture','Documenti da associare'):
  st.markdown('**'+name+'**')
  if report[name]:st.dataframe(pd.DataFrame(report[name]),hide_index=True,use_container_width=True)
 st.caption('I documenti non associati non hanno ancora una CC attribuita: sono inclusi per divisione e struttura, anche se il loro periodo non coincide con l’anno intervento selezionato. Non sono automaticamente materiale non fatturato.')
st.caption('Chiuso con ordine e fattura = tutte le quantità associate e nessuna revisione pendente. La conferma della chiusura mensile avviene in Chiusura guidata.')
