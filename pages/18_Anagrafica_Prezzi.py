import streamlit as st
from orthoflow_branding import configure_page
configure_page(page_title='Anagrafica prezzi · P.M. Medical',page_icon='💷',layout='wide')
permissions=set(st.session_state.get('permessi',[]) or [])
allowed=str(st.session_state.get('ruolo','')).strip().lower() in ('admin','amministrazione') or bool(permissions & {'DIREZIONE','AMMINISTRAZIONE'})
if not st.session_state.get('user') or not allowed:
    st.error('Accesso non autorizzato.');st.stop()
from price_registry_runtime import current_registry
current_registry().render_registry()
