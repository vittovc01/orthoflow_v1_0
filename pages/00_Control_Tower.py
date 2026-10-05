from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo
import os

import pandas as pd
import streamlit as st
from supabase import create_client
from home_data import load_home
from orthoflow_branding import configure_page

configure_page(page_title='Home · OrthoFlow', layout='wide')

# Preserve role landing and one direct-URL authorization check.
perms = set(st.session_state.get('permessi', []) or [])
role = str(st.session_state.get('ruolo', ''))
director = role == 'Admin' or 'DIREZIONE' in perms
if not st.session_state.get('user'):
    st.error('Sessione non autenticata.'); st.stop()
if not director:
    landing = {'CORRIERE': 'pages/09_Corrieri.py', 'LOGISTICA': 'pages/01_WMS.py',
               'AGENTE': 'pages/05_Scarico_Sala_AI.py', 'AMMINISTRAZIONE': 'pages/06_Gestione_Interventi.py'}
    if len(perms) == 1 and next(iter(perms)) in landing:
        st.switch_page(landing[next(iter(perms))])
    st.error('Non sei autorizzato ad accedere a questa area.'); st.stop()

st.markdown('<style>' + (Path(__file__).parents[1] / 'assets/home.css').read_text() + '</style>', unsafe_allow_html=True)

@st.cache_resource
def sb():
    url = st.secrets.get('SUPABASE_URL') or os.getenv('SUPABASE_URL')
    key = (st.secrets.get('SUPABASE_SERVICE_KEY') or st.secrets.get('SUPABASE_SERVICE_ROLE_KEY')
           or st.secrets.get('SUPABASE_KEY') or os.getenv('SUPABASE_SERVICE_KEY'))
    if not url or not key:
        st.error('Collegamento dati non configurato.'); st.stop()
    return create_client(str(url).rstrip('/'), str(key))

now = datetime.now(ZoneInfo('Europe/Rome'))
today = now.date()
# A session-local short cache avoids repeated loads while navigating. Never cache writes.
if st.session_state.get('_home_snapshot_day') != today.isoformat():
    st.session_state.pop('_home_snapshot', None)
header, refresh = st.columns([6, 1], vertical_alignment='center')
with header:
    st.markdown(f'<div class="home-heading"><div class="home-eyebrow">ORTHOFLOW / OPERATIVITÀ</div><h1>Panoramica operativa</h1><p>Il lavoro da seguire, tutto a portata di mano.</p></div>', unsafe_allow_html=True)
with refresh:
    st.markdown(f'<div class="home-date">{today.strftime("%d.%m.%Y")}</div>', unsafe_allow_html=True)
    if st.button('Aggiorna', icon=':material/refresh:', use_container_width=True):
        st.session_state.pop('_home_snapshot', None)
previous = st.session_state.get('_home_snapshot_at')
if '_home_snapshot' not in st.session_state or not previous or (now - previous).total_seconds() > 30:
    st.session_state['_home_snapshot'] = load_home(sb(), today)
    st.session_state['_home_snapshot_at'] = now
    st.session_state['_home_snapshot_day'] = today.isoformat()
data = st.session_state['_home_snapshot']


def number(value):
    return '—' if value is None else f'{int(value):,}'.replace(',', '.')


def metric(label, value, caption, icon, accent=''):
    st.markdown(f'<div class="home-metric {accent}"><div class="home-metric-top"><span>{escape(label)}</span><span class="home-symbol">{icon}</span></div><strong>{number(value)}</strong><small>{escape(caption)}</small></div>', unsafe_allow_html=True)


missions = data['missions']
pending = None if missions is None else len(missions)
mission_today = [] if missions is None else [m for m in missions if m.get('data_missione') == today.isoformat()]
icons = {
    'calendar': '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M3 10h18M8 3v4M16 3v4m-8 8h3"/></svg>',
    'activity': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12h4l3-7 4 14 3-7h4"/></svg>',
    'truck': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 5h12v12H3zm12 4h3l3 4v4h-6"/><circle cx="7" cy="18" r="2"/><circle cx="18" cy="18" r="2"/></svg>',
    'alert': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 10 18H2zM12 9v5m0 3v1"/></svg>'}
for col, (label, value, caption, icon, accent) in zip(st.columns(4), [
    ('Interventi di oggi', data['today'], 'Data dell’intervento', 'activity', 'featured'),
    ('Interventi del mese', data['month'], today.strftime('%m / %Y'), 'calendar', ''),
    ('Missioni da completare', pending, f'{len(mission_today)} previste oggi' if missions is not None else 'Dati non disponibili', 'truck', ''),
    ('Anomalie da verificare', data['anomalies'], 'Prezzi e giacenze', 'alert', 'warning' if data['anomalies'] else ''),
]):
    with col:
        metric(label, value, caption, icons[icon], accent)
if data['errors']:
    st.warning('Dati non disponibili: ' + ', '.join(data['errors']) + '. Premi Aggiorna per riprovare.')

st.markdown('<div class="home-section"><h2>Inizia un’attività</h2><span>Le funzioni che usi ogni giorno</span></div>', unsafe_allow_html=True)
actions = [
    ('pages/05_Scarico_Sala_AI.py', 'Nuovo scarico sala', 'Analizza foto e PDF degli impianti', ':material/document_scanner:'),
    ('pages/04_DDT_Carico_v2.py', 'Carica un DDT', 'Registra il materiale in entrata', ':material/upload_file:'),
    ('pages/06_Gestione_Interventi.py', 'Gestisci interventi', 'Consulta e correggi gli scarichi', ':material/assignment:'),
    ('pages/09_Corrieri.py', 'Missioni corrieri', 'Organizza consegne e ritiri', ':material/local_shipping:')]
for col, (page, label, caption, icon) in zip(st.columns(4), actions):
    with col.container(border=True):
        st.page_link(page, label=label, icon=icon, use_container_width=True)
        st.caption(caption)

left, right = st.columns([1.7, 1], gap='large')
with left:
    with st.container(border=True):
        st.markdown('<div class="home-section"><h2>Ultimi interventi</h2><span>Gli ultimi 6 registrati per data</span></div>', unsafe_allow_html=True)
        recent = data['recent']
        if recent is None:
            st.info('Elenco momentaneamente non disponibile.')
        elif not recent:
            st.markdown('<div class="home-empty">Nessun intervento registrato.<br><small>Inizia da Nuovo scarico sala.</small></div>', unsafe_allow_html=True)
        else:
            # Patient/cartella identifiers and prices belong to the detailed pages.
            for item in recent:
                label = item.get('cliente') or item.get('struttura') or 'Struttura non indicata'
                day = str(item.get('data_intervento') or '')
                try:
                    day = datetime.strptime(day, '%Y-%m-%d').strftime('%d/%m')
                except ValueError:
                    day = '—'
                st.markdown(f'<div class="home-activity"><div class="home-day">{escape(day)}</div><div><strong>{escape(str(label))}</strong><small>{escape(str(item.get("agente") or "Agente non indicato"))} · {escape(str(item.get("linea") or "Linea non indicata"))}</small></div><span class="home-record">#{escape(str(item["id"]))}</span></div>', unsafe_allow_html=True)
        st.page_link('pages/06_Gestione_Interventi.py', label='Apri tutti gli interventi', icon=':material/arrow_forward:', use_container_width=True)
    with st.container(border=True):
        st.markdown('<div class="home-section"><h2>Magazzino</h2><span>Disponibilità e tracciabilità</span></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="home-stock"><strong>{number(data["lots"])}</strong><div>Lotti / posizioni con quantità positiva<small>Conteggio completo per codice, lotto e magazzino</small></div></div>', unsafe_allow_html=True)
        st.page_link('pages/01_WMS.py', label='Apri magazzino e scanner', icon=':material/inventory_2:', use_container_width=True)
with right:
    with st.container(border=True):
        st.markdown('<div class="home-section"><h2>Da seguire</h2><span>Controlli operativi</span></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="home-check"><span>Anomalie prezzi</span><strong>{number(data["price_anomalies"])}</strong></div><div class="home-check"><span>Anomalie giacenza</span><strong>{number(data["stock_anomalies"])}</strong></div>', unsafe_allow_html=True)
        st.page_link('pages/14_Anomalie_Prezzi.py', label='Verifica le anomalie', icon=':material/fact_check:', use_container_width=True)
        st.divider()
        expiries = data['expiring']
        if expiries is None:
            st.info('Scadenze momentaneamente non disponibili.')
        else:
            expired = sum(str(x['scadenza']) < today.isoformat() for x in expiries)
            urgent = sum(today.isoformat() <= str(x['scadenza']) <= (today + timedelta(days=30)).isoformat() for x in expiries)
            later = len(expiries) - expired - urgent
            st.markdown(f'<div class="home-check"><span><i class="home-dot red"></i>Lotti scaduti</span><strong>{number(expired)}</strong></div><div class="home-check"><span><i class="home-dot amber"></i>In scadenza entro 30 giorni</span><strong>{number(urgent)}</strong></div><div class="home-check"><span><i class="home-dot green"></i>Tra 31 e 90 giorni</span><strong>{number(later)}</strong></div>', unsafe_allow_html=True)
            if not expiries:
                st.caption('Nessun lotto con quantità positiva in scadenza entro 90 giorni.')
            else:
                with st.expander('Mostra codici e lotti in scadenza'):
                    st.dataframe(pd.DataFrame(expiries).drop(columns=['id']).rename(columns={'codice':'Codice','lotto':'Lotto','scadenza':'Scadenza','quantita':'Quantità','codice_magazzino':'Magazzino'}), hide_index=True, use_container_width=True)
        st.page_link('pages/01_WMS.py', label='Controlla disponibilità e lotti', icon=':material/inventory_2:', use_container_width=True)
    with st.container(border=True):
        st.markdown('<div class="home-section"><h2>Consegne e ritiri</h2></div>', unsafe_allow_html=True)
        if missions is None:
            st.caption('Missioni momentaneamente non disponibili.')
        elif not missions:
            st.caption('Nessuna missione da completare.')
        else:
            for mission in missions[:3]:
                st.markdown(f'<div class="home-mission"><strong>{escape(str(mission.get("codice") or "Missione"))}</strong><small>{escape(str(mission.get("tipo") or ""))} · {escape(str(mission.get("data_missione") or ""))}</small><span>{escape(str(mission.get("stato") or "").replace("_", " ").capitalize())}</span></div>', unsafe_allow_html=True)
        st.page_link('pages/09_Corrieri.py', label='Apri le missioni', icon=':material/arrow_forward:', use_container_width=True)

with st.expander('Dettagli di utilizzo OCR'):
    st.caption('Ultime 50 scansioni registrate. Il saldo effettivo è disponibile sulla piattaforma OpenAI.')
    try:
        usage = sb().table('ocr_usage').select('created_at,utente,modulo,modello,file_tipo,total_tokens,costo_usd').order('created_at', desc=True).limit(50).execute().data or []
        if usage:
            st.dataframe(pd.DataFrame(usage), hide_index=True, use_container_width=True)
        else:
            st.caption('Nessuna scansione registrata.')
    except Exception:
        st.info('Dettagli OCR momentaneamente non disponibili.')

st.markdown(f'<div class="home-footer">Orthopedic Service · OrthoFlow<span>Dati aggiornati alle {st.session_state["_home_snapshot_at"].strftime("%H:%M:%S")}</span></div>', unsafe_allow_html=True)
