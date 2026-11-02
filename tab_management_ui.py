"""Shared TAB screens; one accounting ledger, no legacy intervention/stock writes."""
import os
import pandas as pd
import streamlit as st
from jj_closures import read_all
from jj_data import read_ledger as tab_records
from jj_runtime import current_reconciliation
from jj_status_runtime import current_status
from jj_report_runtime import current_reports
from tab_agents import payload_agent
from tab_management import management_report,customer_code

@st.cache_resource
def tab_backend():
    from supabase import create_client
    url=st.secrets.get('SUPABASE_URL') or os.getenv('SUPABASE_URL')
    key=st.secrets.get('SUPABASE_SERVICE_KEY') or os.getenv('SUPABASE_SERVICE_KEY')
    if not url or not key:raise RuntimeError('Configurare la connessione server del modulo TAB')
    return create_client(str(url).rstrip('/'),str(key))

@st.cache_data(ttl=30,max_entries=2)
def tab_catalogs(_client):
    return [read_all(_client,name).to_dict('records') for name in ('clienti','offerte_header','offerte_clienti','offerte_prezzi')]

def refresh():
    tab_records.clear();tab_catalogs.clear()

def import_tab(client,records,links,customers,division):
    with st.expander('Carica / aggiorna TAB '+division.title(),expanded=not any(r['kind']=='IMPIANTO' and r['division']==division for r in records)):
        st.caption('Carica il file cumulativo o giornaliero. I documenti già acquisiti vengono aggiornati, senza sommare di nuovo le quantità e senza movimenti di magazzino. Le righe assenti dal file non vengono cancellate.')
        uploaded=st.file_uploader('TAB '+division.title(),type=['xlsx','xls','csv'],key='management_tab_'+division)
        if not uploaded:return
        context=[r for r in records if r['division']==division]
        try:
            prepared=current_reconciliation().prepare_tab(uploaded.getvalue(),uploaded.name,division,context,customers=customers)
            old={r['source_key']:r for r in context if r['kind']=='IMPIANTO'}
            business=lambda p:{**p,'lines':[{k:v for k,v in l.items() if k!='source_rows'} for l in p['lines']]}
            preview=[]
            for r in prepared:
                before=old.get(r['source_key']);p=r['payload']
                changed=before is not None and business(before['payload'])!=business(p)
                linked=before is not None and any(not l.get('revoked_at') and l['implant_id']==before['id'] for l in links)
                preview.append({'Documento':r['source_key'],'Struttura':p['customer'],'CC':p['encounter'],'Data intervento':p['event_date'],
                  'Agente':payload_agent(p),'Pezzi':sum(l['quantity'] for l in p['lines']),
                  'Esito':'Nuovo' if before is None else 'Revisione da verificare' if changed and linked else 'Aggiornato' if changed else 'Invariato',
                  'Da verificare':', '.join(k for k,v in [('presidio',p.get('cac')),('CC',p.get('encounter')),('data',p.get('event_date'))] if not v)})
            st.write(f"{len(prepared)} documenti · {sum(x['Pezzi'] for x in preview)} pezzi")
            st.dataframe(pd.DataFrame(preview),hide_index=True,use_container_width=True)
            st.caption('CC, date o presidi mancanti restano da verificare. Le modifiche ai documenti già associati richiedono la revisione dei collegamenti.')
            if st.button('Conferma importazione TAB '+division.title(),type='primary'):
                user=st.session_state.get('user');actor=str(user.get('email') or user.get('username') or user.get('id')) if isinstance(user,dict) else str(user)
                result=client.rpc('jj_import_records',{'p_kind':'IMPIANTO','p_division':division,'p_file':uploaded.name,'p_records':prepared,'p_actor':actor}).execute().data
                st.session_state['tab_import_message']='Importazione completata: '+', '.join(f'{result.get(k,0)} {label}' for k,label in [('nuovi','nuovi'),('aggiornati','aggiornati'),('invariati','invariati'),('revisioni_da_verificare','revisioni da verificare')])
                refresh();st.rerun()
        except Exception as exc:st.error('TAB non acquisito: '+str(getattr(exc,'message',None) or exc))

def verify_tab_metadata(client,records,links,customers,documents,division):
    engine=current_reconciliation()
    with st.expander('Verifica struttura, CC e data'):
        available=[r for r in records if r['kind']=='IMPIANTO' and r['division']==division and r['source_key'] in documents]
        rid=st.selectbox('Documento TAB da verificare',[r['id'] for r in available],format_func=lambda key:next(r['source_key'] for r in available if r['id']==key),key='verify_tab_doc_'+division)
        record=next(r for r in available if r['id']==rid);p=record['payload']
        if record.get('pending_payload'):
            st.warning('Il documento ha una revisione pendente: verificala negli strumenti avanzati della Chiusura guidata prima di altre correzioni.');return
        choices={engine.text(c['codice_cliente']):c for c in customers if engine.text(c.get('codice_cliente'))}
        current,_=customer_code(p,customers)
        code=st.selectbox('Struttura verificata',list(choices),index=list(choices).index(current) if current in choices else None,
          format_func=lambda key:(engine.text(choices[key].get('descrizione')) or engine.text(choices[key].get('descrizione_cliente')))+' · '+key,key='verify_tab_customer_'+str(rid))
        accounts=engine.accounts([r for r in records if r['division']==division]);current_cac=p.get('cac') if code==current else ''
        cac=st.selectbox('Presidio J&J per gli abbinamenti',list(accounts),index=list(accounts).index(current_cac) if current_cac in accounts else None,
          format_func=lambda key:accounts[key]+' · '+key,key='verify_tab_cac_'+str(rid)+'_'+str(code))
        st.caption('Il codice struttura interno serve per le offerte; il presidio J&J serve per ordini e fatture. Un presidio non ancora assegnato resta da verificare.')
        cc=st.text_input('CC verificata',value=p.get('encounter',''),key='verify_tab_cc_'+str(rid))
        event=st.text_input('Data verificata (AAAA-MM-GG)',value=p.get('event_date',''),key='verify_tab_event_'+str(rid))
        if any(not l.get('revoked_at') and l['implant_id']==rid for l in links):st.warning('Salvare una correzione richiede di rivedere gli abbinamenti già confermati di questo documento. La cronologia è conservata.')
        checked=st.checkbox('Ho verificato i dati inseriti',key='verify_tab_checked_'+str(rid))
        if st.button('Salva verifica TAB',disabled=not code or not checked,key='verify_tab_save_'+str(rid)):
            try:
                when=engine.date(event)
                if engine.text(event) and not when:raise ValueError('Data non valida')
                name=engine.text(choices[code].get('descrizione')) or engine.text(choices[code].get('descrizione_cliente'))
                payload={**p,'source_customer':p.get('source_customer') or p['customer'],'customer':name,'customer_code':code,
                  'cac':cac or '','encounter':cc.strip(),'event_date':when,'lines':[{**l,'customer':name,'cac':cac or ''} for l in p['lines']]}
                if payload==p:st.info('Nessuna modifica da salvare.');return
                user=st.session_state.get('user');actor=str(user.get('email') or user.get('username') or user.get('id')) if isinstance(user,dict) else str(user)
                client.rpc('jj_review_record',{'p_id':rid,'p_action':'EDIT','p_payload':payload,'p_note':'Verifica struttura/CC/data in Gestione Interventi TAB','p_actor':actor}).execute()
                refresh();st.rerun()
            except Exception as exc:st.error('Verifica non salvata: '+str(getattr(exc,'message',None) or exc))

def render_tab_management(client=None,analytics=False,records=None):
    client=client or tab_backend()
    try:
        if records is None:records,links=tab_records(client)
        else:_,links=tab_records(client)
        customers,headers,connections,prices=tab_catalogs(client)
    except Exception:
        st.error('Dati TAB o anagrafiche non disponibili. Riprova: non vengono mostrati totali parziali.');st.stop()
    if analytics:st.title('Controllo di Gestione · TAB')
    else:st.header('Interventi dal gestionale')
    st.caption('Fonte principale: TAB del gestionale. Gli scarichi storici sono consultabili separatamente e non vengono sommati a questi dati. Nessun movimento di magazzino viene generato.')
    if st.button('Aggiorna dati TAB',key='refresh_tab_'+str(analytics)):
        refresh();st.rerun()
    division=st.radio('Linea TAB',['Tutte','TRAUMA','PROTESICA'] if analytics else ['TRAUMA','PROTESICA'],horizontal=True,key='management_division_'+str(analytics))
    if not analytics:
        import_tab(client,records,links,customers,division)
    if st.session_state.get('tab_import_message'):st.success(st.session_state.pop('tab_import_message'))
    scope=[r for r in records if r['kind']=='IMPIANTO' and (division=='Tutte' or r['division']==division)]
    if not scope:st.info('Nessun TAB caricato per questa linea. Caricalo da Gestione Interventi → Interventi TAB.');return
    cols=st.columns(3)
    structure=cols[0].selectbox('Struttura TAB',['Tutte']+sorted({r['payload'].get('customer','') for r in scope}),key='tab_structure_'+str(analytics)+division)
    year=cols[1].selectbox('Anno TAB',['Tutti']+sorted({r['payload']['event_date'][:4] for r in scope if r['payload'].get('event_date')},reverse=True),key='tab_year_'+str(analytics)+division)
    agent=cols[2].selectbox('Agente TAB',['Tutti']+sorted({payload_agent(r['payload']) for r in scope}),key='tab_agent_'+str(analytics)+division)
    report=management_report(records,links,customers,headers,connections,prices,current_status().build_status,
      None if division=='Tutte' else division,None if structure=='Tutte' else structure,None if year=='Tutti' else year,None if agent=='Tutti' else agent)
    rows=report['Prodotti TAB'];heads=report['Interventi TAB']
    value=sum(r['Valore atteso'] for r in rows if r['Valore atteso'] is not None);missing=sum(r['Valore atteso'] is None for r in rows)
    for col,label,data in zip(st.columns(4),('Interventi TAB','Pezzi','Valore atteso valorizzato','Righe senza prezzo'),(len(heads),sum(r['Quantità impiantata'] for r in rows),f'€ {value:,.2f}',missing)):
        col.metric(label,data)
    if missing:st.warning(f'{missing} righe non valorizzate: mancano struttura/offerta/prezzo univoci o una data valida. Il valore mostrato riguarda solo le righe valorizzate.')
    exportable={name:[{key:value for key,value in row.items() if key!='ID intervento TAB'} for row in entries] for name,entries in report.items()}
    st.download_button('Scarica Excel gestione TAB',current_reports().excel_report(exportable),'Gestione_TAB_'+division+'.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',type='primary')
    if analytics:
        for title in ('Per struttura','Per agente','Per periodo'):
            st.subheader(title)
            st.dataframe(pd.DataFrame(report[title]),hide_index=True,use_container_width=True)
    else:
        visible=['Divisione','Stato','Stato intervento completo','Struttura','Cartella clinica','Data intervento','Agente','Pezzi impiantati','Pezzi da chiudere','Valore atteso valorizzato','Righe senza prezzo']
        st.dataframe(pd.DataFrame(heads)[[c for c in visible if any(c in h for h in heads)]],hide_index=True,use_container_width=True)
        if heads:
            selected=st.selectbox('Apri intervento TAB',[h['ID intervento TAB'] for h in heads],format_func=lambda key:next(f"{h['Struttura']} · CC {h['Cartella clinica'] or 'da verificare'} · {h['Data intervento'] or 'data mancante'}" for h in heads if h['ID intervento TAB']==key))
            st.dataframe(pd.DataFrame([r for r in rows if r['ID intervento TAB']==selected]).drop(columns=['ID intervento TAB']),hide_index=True,use_container_width=True)
            selected_header=next(h for h in heads if h['ID intervento TAB']==selected)
            verify_tab_metadata(client,records,links,customers,selected_header['Documenti TAB'].split(', '),selected_header['Divisione'])
            st.caption('REF, lotto e quantità provengono dal gestionale: correggili lì e ricarica il TAB. Le verifiche di struttura, CC e data restano conservate se il riferimento del documento non cambia.')
    with st.expander('Prezzi da verificare',expanded=bool(report['Prezzi da verificare'])):
        if report['Prezzi da verificare']:st.dataframe(pd.DataFrame(report['Prezzi da verificare']),hide_index=True,use_container_width=True)
        else:st.caption('Nessuna differenza rilevata nei confronti disponibili.')
    st.caption('Valore atteso da offerta e fatturato associato sono distinti. Per lo stato ordine/fattura consulta Stato interventi. Le analisi per chirurgo non sono previste nel flusso TAB.')

def intervention_source(client):
    try:records,_=tab_records(client)
    except Exception:
        st.error('Impossibile leggere la fonte TAB. Riprova prima di consultare gli interventi.');st.stop()
    has_tab=any(r['kind']=='IMPIANTO' for r in records)
    source=st.radio('Fonte interventi',['Interventi TAB','Scarichi storici da scansione'],index=0 if has_tab else 1,horizontal=True,key='intervention_source')
    if source=='Interventi TAB':render_tab_management(client,records=records);st.stop()
    st.caption('Archivio storico da scansione: le modifiche al materiale possono rettificare il magazzino. Questi dati restano separati dalle analisi TAB.')
