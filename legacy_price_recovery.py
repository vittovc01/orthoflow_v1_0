"""Read the audited recovery report; never reimport historical data on page load."""
import json
import pandas as pd
import streamlit as st

@st.cache_data(ttl=300,max_entries=2)
def recovery_audit(_client):
    rows=_client.table('audit_log').select('dettagli').eq('azione','RECUPERO_PREZZI_STORICI').order('id',desc=True).limit(1).execute().data or []
    if not rows:return None
    value=rows[0]['dettagli']
    return json.loads(value) if isinstance(value,str) else value

LABELS={'RECUPERATO':'Recuperato','GIA_RECUPERATO':'Già recuperato','GIA_PRESENTE':'Prezzo attuale preservato',
 'DA_VERIFICARE_DATI':'Dati storici incompleti o non validi','DA_VERIFICARE_PREZZI_STORICI':'Prezzi storici discordanti',
 'DA_VERIFICARE_PRESIDIO':'Presidio non univoco','DA_VERIFICARE_REF':'REF non univoco','DA_VERIFICARE_OFFERTA':'Prezzo diverso dall’offerta',
 'GESTITO_IN_ANAGRAFICA':'Verificato nella nuova anagrafica','RECUPERABILE':'Recuperabile'}

def recovery_tables(report,verified=(),code=None,division=None):
    rows=[];origins={}
    for item in report.get('dettaglio',[]):
        if code is not None and item['codice_cliente']!=code:continue
        if division is not None and item['linea']!=division:continue
        state=item['stato']
        if state.startswith('DA_VERIFICARE_') and item.get('dal') and item.get('al') and any(
          p['codice_cliente']==item['codice_cliente'] and p['linea']==item['linea'] and p['ref']==item['ref']
          and str(p.get('cac') or '')==str(item.get('cac') or '') and p['dal']<=item['dal'] and p['al']>=item['al'] for p in verified):
            state='GESTITO_IN_ANAGRAFICA'
        rows.append({'Struttura':item['struttura'],'Codice struttura':item['codice_cliente'],'Linea':item['linea'],
          'CAC':item.get('cac',''),'REF':item['ref'],'Anno':item.get('anno'),'Stato':LABELS.get(state,state),
          'Da verificare':state.startswith('DA_VERIFICARE_'),'Prezzi nello storico':' | '.join(sorted({str(p['prezzo']) for p in item.get('provenienza',[])})),
          'Valido dal':item.get('dal'),'Valido al':item.get('al'),'Righe origine':item.get('righe_origine',0),
          'Validità':item.get('nota_validita','')})
        for origin in item.get('provenienza',[]):
            origins[origin['riga_id']]={'Struttura':item['struttura'],'Codice struttura':item['codice_cliente'],
              'Linea':item['linea'],'REF':item['ref'],**origin}
    return {'Esiti recupero':rows,'Origini storiche':list(origins.values())}


def render_recovery_history(client,verified,code,division):
    with st.expander('Recupero prezzi dagli scarichi storici'):
        try:report=recovery_audit(client)
        except Exception:
            st.warning('Report di recupero non disponibile. I prezzi dell’anagrafica sono consultabili sopra.');return
        if not report:st.caption('Nessun recupero storico eseguito.');return
        own=recovery_tables(report,verified,code,division)
        rows=own['Esiti recupero'];pending=sum(r['Da verificare'] for r in rows)
        st.caption('Righe originali conservate. Le validità recuperate seguono l’anno degli interventi di origine; non sono scadenze contrattuali ricostruite. I prezzi già presenti non sono stati sovrascritti.')
        if pending:st.warning(f'{pending} prezzi storici da verificare per questa struttura e linea: consulta il motivo e verifica il prezzo in anagrafica.')
        if rows:st.dataframe(pd.DataFrame(rows),hide_index=True,use_container_width=True)
        else:st.caption('Nessun prezzo storico da recuperare per questa struttura e linea.')
        from jj_report_runtime import current_reports
        st.download_button('Scarica report completo recupero storico',lambda:current_reports().excel_report(recovery_tables(report,verified)),
          'Recupero_Prezzi_Storici.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',on_click='ignore')
