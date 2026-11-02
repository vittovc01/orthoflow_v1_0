import base64
from pathlib import Path
import pandas as pd
import streamlit as st
from supabase import create_client
from orthoflow_branding import configure_page
from jj_closures import read_all
from jj_report_runtime import current_reports
from jj_runtime import current_reconciliation

_reconciliation = current_reconciliation()
prepare_tab,prepare_orders,prepare_month,accounts,proposals,residuals,closing_orders,confirmed_associations,allocation_plan,digest = (
 getattr(_reconciliation,name) for name in ('prepare_tab','prepare_orders','prepare_month','accounts','proposals','residuals','closing_orders','confirmed_associations','allocation_plan','digest'))

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

@st.cache_data(ttl=300)
def prepare_uploaded(kind,content,filename,division,month,context):
 if kind=='IMPIANTO':return prepare_tab(content,filename,division,context)
 if kind=='ORDINE':return prepare_orders(content,filename,division,context)
 return prepare_month(content,filename,division,month)

def parsing_context(rows):
 result=[]
 for r in rows:
  payload={k:v for k,v in r['payload'].items() if k not in ('lines','economic_rows')}
  unique={}
  for l in r['payload']['lines']:
   key=(l.get('cac'),l.get('customer'),l.get('po'))
   unique[key]={k:l.get(k) for k in ('cac','customer','po','aliases') if l.get(k) is not None}
  payload['lines']=list(unique.values())
  result.append({'id':r['id'],'kind':r['kind'],'division':r['division'],'source_key':r['source_key'],'payload':payload})
 return result

user=st.session_state.get('user')
actor=str(user.get('email') or user.get('username') or user.get('id') or 'utente') if isinstance(user,dict) else str(user)
_reports=current_reports()

@st.cache_data(ttl=60,max_entries=6)
def export_report(content):
 return _reports.excel_report(content)

st.title('Chiusura guidata')
st.caption('Carica i tre file, controlla il risultato e conferma il mese. Gli impianti del TAB sono usati per il controllo amministrativo.')
division=st.selectbox('Divisione',['TRAUMA','PROTESICA'],key='recon_division')
try:
 records,links=load_data()
except Exception:
 st.error('Impossibile caricare i dati. Verificare la connessione server del modulo chiusure.');st.stop()
records=[r for r in records if r['division']==division]
counts={kind:sum(r['kind']==kind for r in records) for kind in ('IMPIANTO','CHIUSURA','ORDINE')}
catalog=accounts(records)
st.header('1. Carica i file')
for col,kind,label in zip(st.columns(3),counts,('Documenti TAB','Chiusure mensili','Ordini acquisiti')):
 col.metric(label,counts[kind])
if not records:st.info('Nessun dato caricato. Inizia dal TAB aggiornato, poi carica chiusura mensile e ordini.')
template=Path(__file__).resolve().parents[1]/'templates/modello_ordini_chiusura.b64'
if template.exists():st.download_button('Scarica modello Excel ordini',base64.b64decode(template.read_text()),'Modello_Ordini_Chiusura.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
st.caption('Il PO cliente della chiusura resta distinto dal numero ordine J&J. Il lotto non è richiesto nel file ordini.')

for kind,title,uploadkey in [('IMPIANTO','TAB del gestionale','tab'),('CHIUSURA','Chiusura ufficiale J&J','closure'),('ORDINE','Distinte ordini','orders')]:
 with st.expander(title,expanded=not counts[kind]):
  uploaded=st.file_uploader('Carica Excel o CSV',type=['xlsx','xls','csv'],key='recon_'+uploadkey)
  month=st.date_input('Mese di fatturazione',value=pd.Timestamp.today().replace(day=1).date(),key='recon_month') if kind=='CHIUSURA' else None
  if uploaded:
   try:
    content=uploaded.getvalue()
    prepared=prepare_uploaded(kind,content,uploaded.name,division,str(month),parsing_context(records))
    old={r['source_key']:r for r in records if r['kind']==kind}
    preview=[]
    for r in prepared:
     before=old.get(r['source_key']);p=r['payload']
     status='Nuovo' if before is None else ('Invariato' if before['payload']==p else 'Modificato: collegamenti da rivedere' if before.get('pending_payload') or any(not l.get('revoked_at') and before['id'] in (l['closure_id'],l['order_id'],l['implant_id']) for l in links) else 'Aggiornamento')
     preview.append({'Documento':r['source_key'],'Cliente':p.get('customer',''),'Riferimento':p.get('reference',''),
      'Righe':len(p['lines']),'Pezzi':sum(x['quantity'] for x in p['lines']),
      'Presidio mancante':sum(not x.get('cac') for x in p['lines']),'Esito':status})
    st.dataframe(pd.DataFrame(preview).head(10),hide_index=True,use_container_width=True)
    if len(preview)>10:st.caption(f'Anteprima: 10 documenti su {len(preview)}; il salvataggio acquisisce tutti i documenti.')
    if kind=='IMPIANTO':st.caption('Documenti già presenti aggiornati per tipo, serie, numero e anno. Ripetizioni dello stesso REF e lotto aumentano la quantità. La data intervento è distinta dalla data documento.')
    if kind=='CHIUSURA':
     st.write('Fatturato del file: € '+f"{float(prepared[0]['payload']['invoiced_sales']):,.2f}")
     st.caption(f"Righe fonte: {prepared[0]['payload']['source_row_count']}. Rettifiche economiche conservate: {len(prepared[0]['payload']['economic_rows'])}. Le righe prodotto ripetute sono raggruppate mantenendo tutte le quantità.")
    if st.button('Salva '+title,key='save_'+kind,type='primary'):
     response=backend().rpc('jj_import_records',{'p_kind':kind,'p_division':division,'p_file':uploaded.name,'p_records':prepared,'p_actor':actor}).execute().data
     st.session_state['recon_message']='Importazione completata: '+', '.join(str(response.get(k,0))+' '+label for k,label in [('nuovi','nuovi'),('aggiornati','aggiornati'),('invariati','invariati'),('revisioni_da_verificare','revisioni da verificare')]);load_data.clear();st.rerun()
   except Exception as exc:st.error('File non acquisito: '+str(exc))
if st.session_state.get('recon_message'):st.success(st.session_state.pop('recon_message'))

closures=[r for r in records if r['kind']=='CHIUSURA']
if not closures:
 st.info('Carica e salva la chiusura mensile per vedere il risultato dei controlli.');st.stop()
selected_closure=st.selectbox('Mese da controllare',[r['id'] for r in closures],format_func=lambda i:next(r['source_key'] for r in closures if r['id']==i),key='active_closure')
closing=next(r for r in closures if r['id']==selected_closure)
report=_reports.build_report(records,links,selected_closure)
state=report['status']
st.header('2. Controlla il risultato')
for col,label,value in zip(st.columns(4),('Pezzi associati','Pezzi da associare','Differenze di prezzo','Prezzi non confrontabili'),(state['associated_quantity'],state['open_quantity'],state['price_differences'],state['price_unverified'])):
 col.metric(label,value)
if state['blockers']:
 st.warning('Chiusura non ancora pronta: '+ '; '.join(b['Motivo'] for b in state['blockers'])+'. Il report è scaricabile anche con controlli parziali.')
else:st.success('Tutte le quantità della chiusura sono associate. Puoi procedere alla verifica finale.')
exportable={k:v for k,v in report.items() if k!='status'}
st.download_button('Scarica report completo Excel',export_report(exportable),'Controllo_completo_'+division+'_'+closing['source_key']+'.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',type='primary')
resolve_tab,associated_tab,proposal_tab=st.tabs(['Da risolvere','Associati','Proposta da confermare'])
with resolve_tab:
 open_rows=[r for r in report['Righe chiusura'] if r['Quantità residua']>0]
 if open_rows:
  st.write(f"{state['open_rows']} righe della chiusura · {state['open_quantity']} pezzi · € {state['open_value']:,.2f} ancora da associare.")
  st.dataframe(pd.DataFrame(open_rows)[['Presidio','PO','Fattura','REF','Quantità fatturata','Quantità associata','Quantità residua','Valore residuo','Motivo / azione']],hide_index=True,use_container_width=True)
 else:st.success('Nessuna quantità della chiusura rimasta da associare.')
 with st.expander('Prezzi da verificare',expanded=bool(state['price_differences'])):
  if report['Prezzi da verificare']:st.dataframe(pd.DataFrame(report['Prezzi da verificare']),hide_index=True,use_container_width=True)
  else:st.caption('I prezzi confrontabili coincidono. Nessuno scostamento rilevato.')
 st.caption('Nel report Non associati trovi anche i residui di TAB e ordini di tutte le fonti caricate: possono riferirsi ad altri mesi e non vengono dichiarati non fatturati.')
with associated_tab:
 if report['Associazioni']:st.dataframe(pd.DataFrame(report['Associazioni']),hide_index=True,use_container_width=True)
 else:st.info('Nessuna associazione ancora confermata.')
with proposal_tab:
 st.caption('La proposta usa prima le CC meno recenti dello stesso presidio. Puoi verificarla e confermarla in blocco; la ripartizione non dimostra il lotto fatturato.')
 candidates=state['candidates']
 if candidates and not closing.get('closed_at'):
  frame=pd.DataFrame(candidates);frame.insert(0,'Conferma',False)
  presidio=st.selectbox('Filtra presidio',['Tutti']+sorted(frame['Presidio'].unique().tolist()))
  if presidio!='Tutti':frame=frame[frame['Presidio']==presidio]
  order_ids=frame['order_id'].drop_duplicates().tolist()
  order_labels={r['order_id']:str(r['Ordine'])+' · PO '+str(r['PO']) for r in frame.to_dict('records')}
  selected_order=st.selectbox('Filtra ordine / PO',['Tutti']+order_ids,format_func=lambda x:'Tutti' if x=='Tutti' else order_labels[x])
  if selected_order!='Tutti':frame=frame[frame['order_id']==selected_order]
  mode=st.radio('Modalità di abbinamento',['Proposta automatica','Scelta manuale'],horizontal=True)
  automatic=mode=='Proposta automatica'
  if automatic:
   planned=allocation_plan(records,links,selected_closure,frame.to_dict('records'))
   st.info('Criterio della proposta: prima le CC meno recenti dello stesso presidio. Il server controlla le quantità disponibili su chiusura, ordine e impianto. Nulla viene salvato prima della tua conferma.')
   if not planned:
    st.warning('Nessuna ripartizione automatica disponibile: verificare CC/date mancanti o usare Scelta manuale.')
   else:
    frame=pd.DataFrame(planned)
    st.write(f"Proposta: {len(frame)} collegamenti · {frame['order_id'].nunique()} ordini · {frame['implant_id'].nunique()} documenti CC · {int(frame['quantity'].sum())} pezzi.")
    uncovered=sum(max(0,r['Residuo']) for r in residuals([closing],links) if r['Quantità']>0)-int(frame['quantity'].sum())
    if uncovered>0:st.caption(f'Nel mese resterebbero {uncovered} pezzi fatturati da riconciliare dopo questa proposta, compresi gli ordini fuori dal filtro. Il dettaglio resta nei residui.')
    if any(not r['Univoco'] for r in planned):
     st.warning('Sono presenti alternative compatibili. La ripartizione per data è una proposta da verificare e non dimostra a quale CC sia stato fatturato il lotto. Escludi o correggi le righe non corrette.')
    st.download_button('Scarica proposta completa prima della conferma',frame[[c for c in ('Ordine','PO','Fattura','Presidio','Cartella clinica','REF','Lotto impianto','quantity','Criterio proposta') if c in frame]].to_csv(index=False).encode('utf-8-sig'),'Proposta_ordini_CC_'+division+'.csv','text/csv')
  page=1
  if not automatic and len(frame)>1000:
   page=st.number_input('Pagina delle proposte',min_value=1,max_value=(len(frame)+999)//1000,value=1,step=1,key='candidate_page_'+digest([selected_closure,presidio,selected_order,len(frame)]))
   st.caption('Sono mostrate 1.000 alternative per pagina. Conferma le selezioni della pagina corrente prima di passare alla successiva.')
   frame=frame.iloc[(page-1)*1000:page*1000]
  if not automatic or planned:
   selection='Escludi' if automatic else 'Conferma'
   frame=frame.drop(columns=['Conferma'],errors='ignore');frame.insert(0,selection,False)
   visible=[selection,'Fattura','PO','REF','Presidio','Ordine','Cartella clinica','Documento impianto','Riferimento intervento','Data intervento','Lotto impianto','quantity','Criterio proposta','Alternative compatibili','Riscontro documento','Metodo','Univoco','Differenza prezzo']
   visible=[c for c in visible if c in frame]
   with st.form('confirm_proposals'):
    edited=st.data_editor(frame,column_order=visible,disabled=[c for c in frame.columns if c not in (selection,'quantity')],
      column_config={'quantity':st.column_config.NumberColumn('Quantità da collegare',min_value=1,step=1)},hide_index=True,use_container_width=True,
      key='proposals_'+digest([r.get('updated_at') for r in records]+[len(links),selected_closure,presidio,selected_order,page,mode]))
    checked=st.checkbox('Ho verificato la proposta complessiva e accetto il criterio delle CC meno recenti dove vi sono alternative.' if automatic else 'Ho controllato i collegamenti selezionati. Il lotto dell’ordine può non essere disponibile.')
    if st.form_submit_button('Conferma tutta la proposta' if automatic else 'Conferma collegamenti selezionati',type='primary'):
     if not checked:st.error('Conferma di aver verificato la proposta prima del salvataggio.');st.stop()
     chosen=edited[~edited['Escludi'] if automatic else edited['Conferma']].to_dict('records')
     if not chosen:st.warning('Nessun collegamento da salvare. In modalità manuale seleziona almeno una riga; nella proposta automatica lascia incluse le righe da confermare.');st.stop()
     payload=[{k:r[k] for k in ('closure_id','closure_line','order_id','order_line','implant_id','implant_line','quantity','proposal_criterion') if k in r} for r in chosen]
     try:backend().rpc('jj_confirm_links',{'p_links':payload,'p_actor':actor}).execute();load_data.clear();st.rerun()
     except Exception as exc:st.error('Abbinamenti non salvati: '+str(getattr(exc,'message',None) or exc))
 else:st.info('Nessuna proposta disponibile o mese già chiuso. Le quantità mancanti e le azioni necessarie sono nella scheda Da risolvere.')


with st.expander('Strumenti avanzati: presidi, revisioni e documenti',expanded=False):
 if records:
  st.markdown('**Presidi e revisioni**')
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
     if pd.isna(pd.to_datetime(event,errors='coerce')):raise ValueError('Inserisci una data intervento valida')
     payload={**record['payload'],'cac':cac,'event_date':str(pd.Timestamp(event).date()),'lines':[{**l,'cac':cac} for l in record['payload']['lines']]}
     backend().rpc('jj_review_record',{'p_id':selected,'p_action':'EDIT','p_payload':payload,'p_note':note,'p_actor':actor}).execute();load_data.clear();st.rerun()
    except Exception as exc:st.error(str(exc))
 elif records:st.caption('Nessuna revisione o presidio mancante nei documenti acquisiti.')
 st.markdown('**Ordini e fatture da recuperare**')
 order_list=pd.DataFrame(closing_orders(records,selected_closure))
 st.dataframe(order_list,hide_index=True,use_container_width=True)
 st.download_button('Scarica elenco PO e fatture',order_list.to_csv(index=False).encode('utf-8-sig'),'Elenco_PO_fatture_'+division+'_'+closing['source_key']+'.csv','text/csv')
 st.markdown('**Resi e rettifiche economiche**')
 if report['Resi e rettifiche']:st.dataframe(pd.DataFrame(report['Resi e rettifiche']),hide_index=True,use_container_width=True)
 else:st.caption('Nessun reso o rettifica presente.')
 active=[l for l in links if not l.get('revoked_at') and l['closure_id']==selected_closure]
 if active:
  st.markdown('**Correzione dei collegamenti confermati**')
  undo=st.selectbox('Collegamento da annullare',[l['id'] for l in active])
  reason=st.text_input('Motivo annullamento')
  if st.button('Annulla collegamento',disabled=bool(closing.get('closed_at'))):
   try:backend().rpc('jj_revoke_link',{'p_id':undo,'p_note':reason,'p_actor':actor}).execute();load_data.clear();st.rerun()
   except Exception as exc:st.error(str(getattr(exc,'message',None) or exc))
 if closing.get('closed_at'):
  reopen_note=st.text_input('Motivo riapertura del mese')
  if st.button('Riapri mese',disabled=not reopen_note.strip()):
   try:backend().rpc('jj_review_record',{'p_id':selected_closure,'p_action':'REOPEN','p_payload':None,'p_note':reopen_note,'p_actor':actor}).execute();load_data.clear();st.rerun()
   except Exception as exc:st.error(str(getattr(exc,'message',None) or exc))

st.header('3. Conferma il mese')
if closing.get('closed_at'):st.success('Mese confermato il '+str(closing['closed_at']))
else:
 if state['blockers']:
  st.error('Prima della conferma risolvi questi punti:')
  st.dataframe(pd.DataFrame(state['blockers']),hide_index=True,use_container_width=True)
 if state['price_differences'] or state['price_unverified']:st.caption('Gli avvisi di prezzo sono inclusi nel report e richiedono la tua verifica; non impediscono da soli la chiusura.')
 accepted=st.checkbox('Ho controllato associazioni, prezzi, resi e rettifiche del mese.',disabled=not state['can_close'])
 with st.expander('Aggiungi una nota facoltativa'):
  final_note=st.text_area('Note di chiusura')
 if st.button('Conferma chiusura del mese',disabled=not (accepted and state['can_close']),type='primary'):
  note=f"Verifica finale confermata: associazioni complete; {state['price_differences']} confronti con differenze prezzo; {state['price_unverified']} prezzi non confrontabili; resi e rettifiche controllati."
  if final_note.strip():note+=' '+final_note.strip()
  try:
   backend().rpc('jj_review_record',{'p_id':selected_closure,'p_action':'CLOSE','p_payload':None,'p_note':note,'p_actor':actor}).execute();load_data.clear();st.rerun()
  except Exception as exc:st.error('Chiusura non confermata: '+str(getattr(exc,'message',None) or exc))
