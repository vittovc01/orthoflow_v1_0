import base64
from pathlib import Path
import pandas as pd
import streamlit as st
from supabase import create_client
from orthoflow_branding import configure_page
from jj_closures import read_all
from jj_reconciliation import prepare_tab,prepare_orders,prepare_month,accounts,proposals,residuals,digest

configure_page(page_title='Chiusura guidata · P.M. Medical',page_icon='📋',layout='wide')
if not st.session_state.get('user'):st.switch_page('pages/99_Login.py');st.stop()
permissions=set(st.session_state.get('permessi',[]) or [])
if str(st.session_state.get('ruolo',''))!='Admin' and not {'DIREZIONE','AMMINISTRAZIONE'}&permissions:
 st.error('Accesso non autorizzato.');st.stop()

@st.cache_resource
def backend():
 key=st.secrets.get('SUPABASE_SERVICE_KEY')
 if not key:raise RuntimeError('Configurare la connessione server prima di usare la chiusura guidata')
 return create_client(str(st.secrets['SUPABASE_URL']).rstrip('/'),str(key))

@st.cache_data(ttl=30)
def load_data():
 return (read_all(backend(),'jj_recon_records').to_dict('records'),read_all(backend(),'jj_recon_links').to_dict('records'))

user=st.session_state.get('user')
actor=str(user.get('email') or user.get('username') or user.get('id') or 'utente') if isinstance(user,dict) else str(user)
st.title('Chiusura guidata')
st.caption('Carica impianti, chiusura e ordini. Rivedi gli abbinamenti e conferma il mese. Gli impianti storici sono acquisiti per il controllo amministrativo: il caricamento non esegue nuovi scarichi di magazzino.')
division=st.selectbox('Divisione',['TRAUMA','PROTESICA'],key='recon_division')
try:
 records,links=load_data()
except Exception:
 st.error('Procedura non disponibile: verificare la configurazione server del modulo chiusure.');st.stop()
records=[r for r in records if r['division']==division]
catalog=accounts(records)
template=Path(__file__).resolve().parents[1]/'templates/modello_ordini_chiusura.b64'
if template.exists():st.download_button('Scarica modello Excel ordini',base64.b64decode(template.read_text()),'Modello_Ordini_Chiusura.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
st.info('Il PO cliente non è il numero ordine J&J. Negli ordini senza lotto il collegamento viene proposto per presidio, REF e quantità e richiede la tua conferma.')

for kind,title,uploadkey in [('IMPIANTO','1. Impianti dal gestionale (TAB)','tab'),('CHIUSURA','2. Chiusura ufficiale J&J','closure'),('ORDINE','3. Distinte degli ordini','orders')]:
 with st.expander(title,expanded=True):
  uploaded=st.file_uploader('Carica Excel o CSV',type=['xlsx','xls','csv'],key='recon_'+uploadkey)
  month=st.date_input('Mese di fatturazione',value=pd.Timestamp.today().replace(day=1).date(),key='recon_month') if kind=='CHIUSURA' else None
  if uploaded:
   try:
    content=uploaded.getvalue()
    if kind=='IMPIANTO':prepared=prepare_tab(content,uploaded.name,division,records)
    elif kind=='ORDINE':prepared=prepare_orders(content,uploaded.name,division,records)
    else:prepared=prepare_month(content,uploaded.name,division,str(month))
    old={r['source_key']:r for r in records if r['kind']==kind}
    preview=[]
    for r in prepared:
     before=old.get(r['source_key']);p=r['payload']
     status='Nuovo' if before is None else ('Invariato' if before['payload']==p else 'Modificato: collegamenti da rivedere' if before.get('pending_payload') or any(not l.get('revoked_at') and before['id'] in (l['closure_id'],l['order_id'],l['implant_id']) for l in links) else 'Aggiornamento')
     preview.append({'Documento':r['source_key'],'Cliente':p.get('customer',''),'Riferimento':p.get('reference',''),
      'Righe':len(p['lines']),'Pezzi':sum(x['quantity'] for x in p['lines']),
      'Presidio mancante':sum(not x.get('cac') for x in p['lines']),'Esito':status})
    st.dataframe(pd.DataFrame(preview),hide_index=True,use_container_width=True)
    if kind=='IMPIANTO':st.caption('Documenti già presenti aggiornati per tipo, serie, numero e anno. Ripetizioni dello stesso REF e lotto aumentano la quantità. La data intervento è distinta dalla data documento.')
    if kind=='CHIUSURA':st.write('Fatturato del file: € '+f"{float(prepared[0]['payload']['invoiced_sales']):,.2f}")
    if st.button('Salva '+title[3:],key='save_'+kind,type='primary'):
     response=backend().rpc('jj_import_records',{'p_kind':kind,'p_division':division,'p_file':uploaded.name,'p_records':prepared,'p_actor':actor}).execute().data
     st.session_state['recon_message']=str(response);load_data.clear();st.rerun()
   except Exception as exc:st.error('File non acquisito: '+str(exc))
if st.session_state.get('recon_message'):st.success(st.session_state.pop('recon_message'))

st.subheader('4. Verifica presidi e revisioni')
st.caption('ASL Salerno comprende Sapri, Nocera e Battipaglia: assegnare il presidio al singolo documento. Non viene creata una corrispondenza unica per tutta ASL Salerno.')
unmapped_customers=sorted({r['payload'].get('customer','') for r in records if r['kind']=='IMPIANTO' and not r['payload'].get('cac') and r['payload'].get('customer','').strip().upper()!='ASL SALERNO'})
if unmapped_customers and catalog:
 with st.expander('Assegna il presidio ai clienti: una volta sola'):
  choices={catalog[c]+' · '+c:c for c in catalog}
  customer=st.selectbox('Cliente del gestionale',unmapped_customers,key='map_customer')
  selected_presidio=st.selectbox('Presidio per questo cliente',list(choices),index=None,key='map_presidio')
  st.caption('La scelta si applica ai documenti di questo cliente. Le estrazioni TAB successive riutilizzeranno la corrispondenza. Non usare per un cliente che comprende più presidi.')
  if st.button('Conferma corrispondenza cliente e presidio',disabled=not selected_presidio):
   try:backend().rpc('jj_map_customer',{'p_customer':customer,'p_cac':choices[selected_presidio],'p_division':division,'p_actor':actor}).execute();load_data.clear();st.rerun()
   except Exception as exc:st.error(str(exc))
editable=[r for r in records if r['kind']=='IMPIANTO' and (not r['payload'].get('cac') or not r['payload'].get('event_date')) or r.get('pending_payload')]
if editable:
 labels={r['id']:r['kind']+' · '+r['source_key']+' · '+str(r['payload'].get('customer',''))+' · '+str(r['payload'].get('reference','')) for r in editable}
 selected=st.selectbox('Documento da verificare',list(labels),format_func=lambda i:labels[i],key='review_doc')
 record=next(r for r in editable if r['id']==selected)
 review_payload=record.get('pending_payload') or record['payload']
 st.write(review_payload.get('reference') or record['source_key'])
 st.dataframe(pd.DataFrame(review_payload['lines'])[[c for c in ('ref','lot','quantity','expiry','price','total') if c in pd.DataFrame(review_payload['lines'])]],hide_index=True,use_container_width=True)
 note=st.text_input('Motivazione della verifica',key='review_note')
 if record.get('pending_payload'):
  st.warning('Accettare la revisione annulla i collegamenti precedenti del documento e richiede una nuova riconciliazione. La cronologia viene conservata.')
  if st.button('Accetta revisione e rivedi gli abbinamenti'):
   try:backend().rpc('jj_review_record',{'p_id':selected,'p_action':'ACCEPT_REVISION','p_payload':None,'p_note':note,'p_actor':actor}).execute();load_data.clear();st.rerun()
   except Exception as exc:st.error(str(exc))
 elif record['kind']=='IMPIANTO' and catalog:
  cac=st.selectbox('Presidio corretto',list(catalog),format_func=lambda c:catalog[c]+' · '+c,key='review_cac',index=None)
  event=st.text_input('Data intervento (AAAA-MM-GG)',value=record['payload'].get('event_date',''),key='review_date_'+str(selected)+digest(record['payload']))
  if st.button('Salva presidio e data verificati'):
   try:
    if not cac:raise ValueError('Scegliere il presidio')
    pd.Timestamp(event)
    payload={**record['payload'],'cac':cac,'event_date':str(pd.Timestamp(event).date()),'lines':[{**l,'cac':cac} for l in record['payload']['lines']]}
    backend().rpc('jj_review_record',{'p_id':selected,'p_action':'EDIT','p_payload':payload,'p_note':note,'p_actor':actor}).execute();load_data.clear();st.rerun()
   except Exception as exc:st.error(str(exc))
else:st.caption('Nessuna revisione o presidio mancante nei documenti acquisiti.')

closures=[r for r in records if r['kind']=='CHIUSURA']
if closures:
 selected_closure=st.selectbox('Chiusura da riconciliare',[r['id'] for r in closures],format_func=lambda i:next(r['source_key'] for r in closures if r['id']==i),key='active_closure')
 closing=next(r for r in closures if r['id']==selected_closure)
 st.subheader('5. Abbinamenti da confermare')
 candidates=proposals(records,links,selected_closure)
 if candidates and not closing.get('closed_at'):
  frame=pd.DataFrame(candidates);frame.insert(0,'Conferma',False)
  presidio=st.selectbox('Filtra presidio',['Tutti']+sorted(frame['Presidio'].unique().tolist()))
  if presidio!='Tutti':frame=frame[frame['Presidio']==presidio]
  if len(frame)>1000:st.warning('Molti abbinamenti possibili: filtra per presidio. Sono mostrate le prime 1.000 proposte.');frame=frame.head(1000)
  visible=['Conferma','Fattura','PO','REF','Presidio','Ordine','Documento impianto','Riferimento intervento','Data intervento','Lotto impianto','quantity','Metodo','Univoco','Differenza prezzo']
  with st.form('confirm_proposals'):
   edited=st.data_editor(frame,column_order=visible,disabled=[c for c in frame.columns if c not in ('Conferma','quantity')],
     column_config={'quantity':st.column_config.NumberColumn('Quantità da collegare',min_value=1,step=1)},hide_index=True,use_container_width=True,
     key='proposals_'+digest([r.get('updated_at') for r in records]+[len(links),selected_closure,presidio]))
   checked=st.checkbox('Ho controllato i collegamenti selezionati. Il lotto dell’ordine può non essere disponibile.')
   if st.form_submit_button('Conferma collegamenti selezionati',type='primary'):
    if not checked:st.error('Conferma il controllo dei collegamenti selezionati.');st.stop()
    chosen=edited[edited['Conferma']].to_dict('records')
    payload=[{k:r[k] for k in ('closure_id','closure_line','order_id','order_line','implant_id','implant_line','quantity')} for r in chosen]
    try:backend().rpc('jj_confirm_links',{'p_links':payload,'p_actor':actor}).execute();load_data.clear();st.rerun()
    except Exception as exc:st.error('Abbinamenti non salvati: '+str(exc))
 else:st.caption('Nessuna proposta residua, oppure mese già confermato. Consultare i residui: mancanza di proposte non significa riconciliazione completa.')

 st.subheader('Residui e abbinamenti confermati')
 remaining=pd.DataFrame(residuals(records,links))
 if not remaining.empty:
  st.dataframe(remaining,hide_index=True,use_container_width=True)
  st.download_button('Esporta controllo e residui',remaining.to_csv(index=False).encode('utf-8-sig'),'Residui_'+division+'.csv','text/csv')
 st.caption('Un impianto non riscontrato nelle fonti caricate non viene dichiarato non fatturato. Può riferirsi a un altro mese. Resi e rettifiche economiche sono conservati separatamente e richiedono verifica.')
 active=[l for l in links if not l.get('revoked_at') and l['closure_id']==selected_closure]
 if active:
  by_id={r['id']:r for r in records}
  confirmed=[]
  for l in active:
   c=next(x for x in by_id[l['closure_id']]['payload']['lines'] if x['key']==l['closure_line'])
   o=next(x for x in by_id[l['order_id']]['payload']['lines'] if x['key']==l['order_line'])
   difference=float(c['price'])-float(o['price']) if c.get('price') is not None and o.get('price') is not None else None
   confirmed.append({'Prezzo ordine':o.get('price'),'Prezzo chiusura':c.get('price'),'Differenza unit.':difference,'Collegamento':l['id'],'Fattura':c.get('invoice'),'PO':c.get('po'),'REF':c['ref'],'Documento impianto':by_id[l['implant_id']]['source_key'],'Quantità':l['quantity'],'Metodo':l['method'],'Utente':l['actor'],'Data':l['created_at']})
  st.dataframe(pd.DataFrame(confirmed),hide_index=True,use_container_width=True)
  undo=st.selectbox('Collegamento da annullare',[l['id'] for l in active])
  reason=st.text_input('Motivo annullamento')
  if st.button('Annulla collegamento'):
   try:backend().rpc('jj_revoke_link',{'p_id':undo,'p_note':reason,'p_actor':actor}).execute();load_data.clear();st.rerun()
   except Exception as exc:st.error(str(exc))
 with st.expander('Resi e rettifiche economiche da verificare'):
  returns=[l for l in closing['payload']['lines'] if l['quantity']<0]
  if returns:st.dataframe(pd.DataFrame(returns)[['customer','po','invoice','ref','quantity','total']],hide_index=True)
  economics=closing['payload'].get('economic_rows',[])
  st.write(f'{len(economics)} righe di rettifiche economiche conservate nel file.')
  if economics:st.dataframe(pd.DataFrame([{k:v for k,v in r.items() if k in ('codice','cac','account_name','nis','invoiced_sales')} for r in economics]),hide_index=True)
 final_note=st.text_area('Note di chiusura / documenti di reso e rettifiche verificati')
 accepted=st.checkbox('Ho verificato le righe riconciliate, i resi e le rettifiche economiche di questo mese.')
 if st.button('Riapri mese' if closing.get('closed_at') else 'Conferma chiusura del mese',disabled=not accepted):
  try:
   backend().rpc('jj_review_record',{'p_id':selected_closure,'p_action':'REOPEN' if closing.get('closed_at') else 'CLOSE','p_payload':None,'p_note':final_note,'p_actor':actor}).execute();load_data.clear();st.rerun()
  except Exception as exc:st.error('Chiusura non confermata: '+str(exc))
 if closing.get('closed_at'):st.success('Mese confermato il '+str(closing['closed_at']))
