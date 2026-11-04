"""On-demand AI explanation; no patient data and no background API requests."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
from management_insights import insights,ai_payload,payload_key,analyze


def setting(name,default=''):
    try:value=st.secrets.get(name)
    except Exception:value=None
    return str(value or os.getenv(name) or default).strip()


@st.fragment
def render_insights(report):
    data=insights(report,datetime.now(ZoneInfo('Europe/Rome')).date())
    st.subheader('Priorità e previsioni')
    st.caption('Analisi dei TAB nei filtri selezionati. Nessuna modifica automatica a prezzi, interventi o chiusure.')
    for col,(name,value) in zip(st.columns(3),list(data['Indicatori'].items())[1:]):col.metric(name,value)
    if data['Priorità']:st.dataframe(pd.DataFrame(data['Priorità']),hide_index=True,use_container_width=True)
    else:st.info('Nessuna riga senza prezzo nei filtri selezionati.')
    st.caption('Stima del volume del mese corrente: media degli ultimi tre mesi conclusi consecutivi. Il mese in corso è escluso dalla base; con dati insufficienti o non aggiornati la stima non viene prodotta. Gli scenari sono indicativi, senza stagionalità. Conferma che i TAB dei mesi base siano completi prima di usare la stima.')
    if data['Previsioni']:st.dataframe(pd.DataFrame(data['Previsioni']),hide_index=True,use_container_width=True)
    from jj_report_runtime import current_reports
    tables={k:data[k] for k in ('Mensile strutture','Previsioni','Priorità')}
    st.download_button('Scarica analisi e previsioni Excel',lambda:current_reports().excel_report(tables),
      'Analisi_previsioni_TAB.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',on_click='ignore')
    st.subheader('Analista AI')
    st.caption('Generazione solo su richiesta, con consumo API. Riceve conteggi mensili per struttura, valori economici aggregati, criticità e stime: nessuna cartella clinica, paziente o dettaglio prodotto. Il risultato rimane disponibile per gli stessi dati e filtri in questa sessione.')
    model=setting('OPENAI_MANAGEMENT_MODEL','gpt-6.1-sol')
    key=setting('OPENAI_API_KEY')
    st.caption('Modello: '+model)
    payload=ai_payload(data);fingerprint=payload_key(payload,model)
    state=st.session_state.setdefault('management_ai_results',{})
    existing=state.get(fingerprint)
    if st.button('Genera analisi e consigli AI',disabled=not key or bool(existing),key='management_generate_ai'):
        try:
            from openai import OpenAI
            with st.spinner('Analisi dei dati aggregati…'):
                result=analyze(payload,OpenAI(api_key=key,timeout=45,max_retries=0),model)
            # Bound session memory and retain only successful, matching results.
            if len(state)>=8:state.pop(next(iter(state)))
            state[fingerprint]=result;existing=result
        except Exception:
            st.warning('Analisi AI non disponibile o non completata. I grafici e i dati restano disponibili; puoi riprovare o restringere i filtri.')
    if not key:st.info('Per attivare l’analista AI configura OPENAI_API_KEY sul server. Le analisi e le previsioni numeriche funzionano già senza API.')
    if existing:
        st.markdown(existing['testo'])
        st.caption(f"Modello {existing['modello']} · token input {existing['input_tokens']} · output {existing['output_tokens']}")
        st.download_button('Scarica analisi AI',existing['testo'],'Analisi_gestionale.txt','text/plain',on_click='ignore')
