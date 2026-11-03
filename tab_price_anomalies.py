"""TAB price checks use the management read model, never legacy anomaly rows."""
import pandas as pd
import streamlit as st
from tab_management import management_report,structure_label
from tab_management_ui import tab_records,tab_catalogs,refresh
from jj_runtime import current_reconciliation
from jj_status_runtime import current_status
from jj_report_runtime import current_reports
from tab_agents import payload_agent

def category(row):
    if row['Esito']=='FATTURA DIVERSA DALL’OFFERTA':return 'Differenza fattura / offerta'
    if row['Esito']=='PREZZO FATTURA MANCANTE':return 'Prezzo fattura mancante'
    reason=row.get('Motivo / azione','').lower()
    if 'struttura' in reason:return 'Struttura da verificare'
    if not row.get('Data intervento'):return 'Data intervento da verificare'
    if 'ambiguo' in reason or 'prezzi diversi' in reason:return 'Offerte o REF ambigui'
    return 'Offerta / prezzo da verificare'

def price_checks(report):
    result=[]
    context={(r['Divisione'],r['Documento TAB'],r['REF'],r['Lotto']):r for r in report['Prodotti TAB']}
    for row in report['Prezzi da verificare']:
        own=context.get((row['Divisione'],row.get('Documento TAB'),row.get('REF'),row.get('Lotto')),row)
        result.append({**{k:v for k,v in row.items() if k!='ID intervento TAB'},
          'Struttura':own['Struttura'],'CAC':own.get('CAC',''),'Codice struttura':own.get('Codice struttura',''),
          'Categoria':category(row),
          'Quantità':row.get('Quantità impiantata',row.get('Quantità',0))})
    return result

def grouped_actions(rows):
    grouped={}
    for row in rows:
        key=(row['Divisione'],row['Categoria'],row.get('CAC') or row.get('Codice struttura') or row['Struttura'],row.get('REF'))
        g=grouped.setdefault(key,{'Divisione':row['Divisione'],'Categoria':row['Categoria'],'Struttura':row['Struttura'],
          'Codice struttura':row.get('Codice struttura',''),'CAC':row.get('CAC',''),'REF':row.get('REF'),'Righe interessate':0,
          'Pezzi interessati':0,'Azione':('Verifica struttura / CC / data in Gestione Interventi' if row['Categoria'] in ('Struttura da verificare','Data intervento da verificare') else 'Verifica la fattura e l’offerta della struttura' if row['Categoria'] in ('Differenza fattura / offerta','Prezzo fattura mancante') else 'Completa o correggi l’offerta della struttura in Controllo di Gestione → Offerte')})
        g['Righe interessate']+=1;g['Pezzi interessati']+=row['Quantità']
    return list(grouped.values())

def render_tab_price_anomalies(client_factory,reset_client):
    st.subheader('Prezzi TAB da verificare')
    st.caption('Stessi controlli di Gestione Interventi e Controllo di Gestione: prezzi mancanti, offerte ambigue e differenze fattura/offerta. Le segnalazioni sono ricalcolate dai dati correnti.')
    if st.button('Aggiorna anomalie TAB'):
        refresh()
    def read():
        client=client_factory();records,links=tab_records(client)
        return records,links,tab_catalogs(client)
    try:
        try:records,links,catalogs=read()
        except Exception as exc:
            if str(getattr(exc,'code','')) not in ('PGRST301','PGRST303','401'):raise
            reset_client();refresh();records,links,catalogs=read()
    except Exception:
        st.error('Anomalie TAB non disponibili. Premi Aggiorna anomalie TAB per riprovare; i dati storici sono mostrati separatamente.');return
    customers,headers,connections,prices=catalogs
    division=st.radio('Linea anomalie TAB',['Tutte','TRAUMA','PROTESICA'],horizontal=True,key='anomaly_tab_division')
    scope=[r for r in records if r['kind']=='IMPIANTO' and (division=='Tutte' or r['division']==division)]
    if not scope:
        st.info('Nessun TAB acquisito per questa linea. Caricalo in Gestione Interventi → Interventi TAB.');return
    engine=current_reconciliation();accounts=engine.accounts(records)
    cols=st.columns(3)
    structure=cols[0].selectbox('Struttura anomalie TAB',['Tutte']+sorted({structure_label(r['payload'],customers,accounts) for r in scope}),key='anomaly_tab_structure_'+division)
    year=cols[1].selectbox('Anno anomalie TAB',['Tutti']+sorted({r['payload']['event_date'][:4] for r in scope if r['payload'].get('event_date')},reverse=True),key='anomaly_tab_year_'+division)
    agent=cols[2].selectbox('Agente anomalie TAB',['Tutti']+sorted({payload_agent(r['payload']) for r in scope}),key='anomaly_tab_agent_'+division)
    report=management_report(records,links,customers,headers,connections,prices,current_status().build_status,
      None if division=='Tutte' else division,None if structure=='Tutte' else structure,None if year=='Tutti' else year,None if agent=='Tutti' else agent)
    checks=price_checks(report)
    selected=st.selectbox('Tipo di anomalia TAB',['Tutti']+sorted({r['Categoria'] for r in checks}))
    rows=checks if selected=='Tutti' else [r for r in checks if r['Categoria']==selected]
    for col,label,value in zip(st.columns(4),('Righe TAB senza prezzo','Differenze fattura / offerta','Prezzi fattura mancanti','Segnalazioni TAB'),
      (sum(r['Esito']=='VALORIZZAZIONE DA VERIFICARE' for r in rows),sum(r['Esito']=='FATTURA DIVERSA DALL’OFFERTA' for r in rows),sum(r['Esito']=='PREZZO FATTURA MANCANTE' for r in rows),len(rows))):
        col.metric(label,value)
    actions=grouped_actions(rows)
    summary=report['Riepilogo']+[{'Voce':'Tipo anomalia selezionato','Valore':selected},{'Voce':'Segnalazioni TAB mostrate','Valore':len(rows)}]
    st.download_button('Scarica Excel anomalie TAB',current_reports().excel_report({'Riepilogo':summary,'Anomalie TAB':rows,'Azioni raggruppate':actions}),
      'Anomalie_Prezzi_TAB_'+division+'.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',type='primary')
    if not rows:
        st.success('Nessuna anomalia prezzo TAB nei filtri selezionati.');return
    st.warning(f'{len(rows)} segnalazioni TAB da verificare nei filtri selezionati.')
    columns=['Categoria','Divisione','Struttura','Cartella clinica','Data intervento','Agente','REF','Descrizione','Lotto','Quantità','Prezzo offerta','Prezzo chiusura','Differenza unit.','Motivo / azione']
    st.dataframe(pd.DataFrame(rows)[[k for k in columns if any(k in r for r in rows)]],hide_index=True,use_container_width=True)
    with st.expander('Azioni per struttura e REF'):
        st.dataframe(pd.DataFrame(actions),hide_index=True,use_container_width=True)
    st.info('Per i prezzi TAB completa o correggi l’offerta in Controllo di Gestione → Offerte, poi premi Aggiorna anomalie TAB: tutte le righe corrispondenti vengono ricalcolate. Per struttura, CC e data usa la verifica in Gestione Interventi. La regolarizzazione degli scarichi storici qui sotto riguarda solo lo storico.')
