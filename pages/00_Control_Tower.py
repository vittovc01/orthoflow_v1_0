from datetime import date
import pandas as pd
import streamlit as st
from supabase import create_client

st.set_page_config(page_title='OrthoFlow Control Tower', page_icon='🛰️', layout='wide')

st.markdown('''
<style>
.block-container{max-width:1500px;padding-top:1.1rem;padding-bottom:3rem}
[data-testid="stAppViewContainer"]{background:radial-gradient(circle at 15% 0%,rgba(23,128,95,.10),transparent 28%),linear-gradient(180deg,#F8FBFA 0%,#F3F7F6 100%)}
[data-testid="stSidebar"]{background:#0B1F2A;border-right:1px solid rgba(255,255,255,.08)}
[data-testid="stSidebar"] *{color:#F2FAF7!important}
.ct-hero{padding:26px 28px;border-radius:24px;background:linear-gradient(135deg,#0B1F2A,#123B41 55%,#17805F);color:white;box-shadow:0 18px 40px rgba(11,31,42,.14);margin-bottom:20px}
.ct-kicker{font-size:.78rem;letter-spacing:.16em;text-transform:uppercase;opacity:.72;font-weight:800}
.ct-hero h1{font-size:2.15rem;margin:.35rem 0 .45rem;font-weight:800;letter-spacing:-.035em;color:white!important}
.ct-hero p{margin:0;opacity:.82;font-size:1rem}
[data-testid="stMetric"]{background:white;border:1px solid rgba(16,38,46,.08);border-radius:18px;padding:16px 18px;box-shadow:0 8px 24px rgba(16,38,46,.05);min-height:108px}
[data-testid="stMetricLabel"]{font-weight:700;color:#4D666B}
[data-testid="stMetricValue"]{font-weight:800;color:#10262E}
.ct-section{margin-top:8px;margin-bottom:8px;font-size:1.05rem;font-weight:800;color:#10262E}
.stButton>button,.stLinkButton>a{border-radius:13px!important;min-height:46px;font-weight:750}
[data-testid="stDataFrame"]{border:1px solid rgba(16,38,46,.08);border-radius:16px;overflow:hidden}
@media(max-width:760px){.block-container{padding:.8rem}.ct-hero{padding:20px}.ct-hero h1{font-size:1.65rem}[data-testid="stMetric"]{min-height:92px;padding:13px}}
</style>
''', unsafe_allow_html=True)

def sb():
    url=st.secrets.get('SUPABASE_URL')
    key=st.secrets.get('SUPABASE_SERVICE_KEY') or st.secrets.get('SUPABASE_ANON_KEY') or st.secrets.get('SUPABASE_KEY')
    if not url or not key:
        st.error('Supabase non configurato nei Secrets.'); st.stop()
    return create_client(str(url).rstrip('/'),str(key))

def user(): return str(st.session_state.get('user',''))
def role(): return str(st.session_state.get('ruolo',''))
def agent(): return str(st.session_state.get('agente_nome',''))

if not user():
    st.warning('Accedi prima dalla pagina principale di OrthoFlow.'); st.stop()

def get_table(name):
    try: return pd.DataFrame(sb().table(name).select('*').execute().data or [])
    except Exception: return pd.DataFrame()

def euro(v):
    try: return f"€ {float(v):,.2f}".replace(',', 'X').replace('.', ',').replace('X','.')
    except Exception: return '€ 0,00'

st.markdown(f'''<div class="ct-hero"><div class="ct-kicker">ORTHOFLOW CONTROL TOWER</div><h1>Command center operativo</h1><p>{role()} · {agent() or user()} · {date.today().strftime('%d/%m/%Y')}</p></div>''',unsafe_allow_html=True)

interventi=get_table('interventi'); righe=get_table('righe_intervento'); giacenze=get_table('giacenze'); anomalie=get_table('anomalie'); movimenti=get_table('movimenti_magazzino')
if role()=='Agente' and agent():
    if not interventi.empty and 'agente' in interventi.columns: interventi=interventi[interventi['agente'].astype(str).str.casefold()==agent().casefold()]
    if not righe.empty and 'intervento_id' in righe.columns and not interventi.empty:
        ids=set(interventi['id'].astype(str)); righe=righe[righe['intervento_id'].astype(str).isin(ids)]
fatt=0.0
if not righe.empty and 'totale' in righe.columns: fatt=pd.to_numeric(righe['totale'],errors='coerce').fillna(0).sum()
aperti=len(anomalie) if not anomalie.empty else 0
if not anomalie.empty and 'risolta' in anomalie.columns: aperti=len(anomalie[~anomalie['risolta'].fillna(False).astype(bool)])

c1,c2,c3,c4,c5=st.columns(5)
c1.metric('Fatturato',euro(fatt)); c2.metric('Interventi',len(interventi)); c3.metric('Giacenze',len(giacenze) if role()!='Agente' else '—'); c4.metric('Anomalie aperte',aperti); c5.metric('Movimenti',len(movimenti) if role() in {'Admin','Magazzino'} else '—')

st.markdown('<div class="ct-section">Accessi rapidi</div>',unsafe_allow_html=True)
if role() in {'Admin','Magazzino'}:
    a,b,c=st.columns(3)
    a.page_link('pages/01_WMS.py',label='📦 Scanner & WMS',use_container_width=True)
    b.page_link('pages/02_QR_Scaffali.py',label='🏷️ QR Scaffali',use_container_width=True)
    c.page_link('pages/03_Gestione_Scaffale.py',label='📚 Gestione Scaffale',use_container_width=True)
else:
    st.info('Usa la voce Gestionale nel menu laterale per Scarico sala, Cartella clinica e attività operative.')

if role() in {'Admin','Magazzino'}:
    st.markdown('<div class="ct-section">Logistica in evidenza</div>',unsafe_allow_html=True)
    try: sc=pd.DataFrame(sb().table('v_scadenze_ubicazioni').select('*').execute().data or [])
    except Exception: sc=pd.DataFrame()
    x1,x2,x3=st.columns(3)
    if not sc.empty:
        x1.metric('Scaduti',len(sc[sc['stato_scadenza']=='SCADUTO'])); x2.metric('Urgenti ≤30 gg',len(sc[sc['stato_scadenza']=='URGENTE'])); x3.metric('Attenzione ≤90 gg',len(sc[sc['stato_scadenza']=='ATTENZIONE']))
        priority=sc[sc['stato_scadenza'].isin(['SCADUTO','URGENTE','ATTENZIONE'])].copy()
        if not priority.empty:
            cols=[c for c in ['codice','descrizione','lotto','scadenza','quantita_disponibile','codice_magazzino','corsia','scaffale','ripiano','posizione'] if c in priority.columns]
            st.dataframe(priority[cols].head(30),use_container_width=True,hide_index=True)
        else: st.success('Nessuna scadenza critica nelle ubicazioni registrate.')
    else:
        x1.metric('Scaduti',0); x2.metric('Urgenti ≤30 gg',0); x3.metric('Attenzione ≤90 gg',0)
        st.info('Le metriche logistiche compariranno quando inizierai a ubicare i prodotti sugli scaffali.')

st.markdown('<div class="ct-section">Attività recente</div>',unsafe_allow_html=True)
if role() in {'Admin','Magazzino'} and not movimenti.empty:
    cols=[c for c in ['data_movimento','tipo_movimento','codice_magazzino','codice','lotto','quantita','utente'] if c in movimenti.columns]
    st.dataframe(movimenti[cols].tail(20).iloc[::-1],use_container_width=True,hide_index=True)
elif not interventi.empty:
    cols=[c for c in ['data_intervento','cliente','agente','linea','fatturato'] if c in interventi.columns]
    st.dataframe(interventi[cols].tail(20).iloc[::-1],use_container_width=True,hide_index=True)
else: st.info('Nessuna attività recente da mostrare.')
