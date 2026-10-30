"""Retired reconciliation screen. No database access or legacy imports."""
import streamlit as st
from orthoflow_branding import configure_page

configure_page(page_title="Chiusura guidata · P.M. Medical", page_icon="📋", layout="wide")
if not st.session_state.get("user"):
    st.switch_page("pages/99_Login.py")
    st.stop()
permissions = set(st.session_state.get("permessi", []) or [])
if str(st.session_state.get("ruolo", "")) != "Admin" and not {"DIREZIONE", "AMMINISTRAZIONE"} & permissions:
    st.error("Accesso non autorizzato.")
    st.stop()
st.info("Il controllo ordini è ora incluso in Chiusura guidata. Usa questa unica sezione per caricare TAB, chiusure e ordini e verificare gli incroci.")
st.markdown("[Apri Chiusura guidata](./chiusura-guidata)")
