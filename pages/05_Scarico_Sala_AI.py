import runpy
import streamlit as st

# P.M. Medical permission gate
_p=set(st.session_state.get("permessi",[]) or [])
_ok=str(st.session_state.get("ruolo",""))=="Admin" or "DIREZIONE" in _p or bool(_p.intersection(["OPERATIVITA","AGENTE"]))
if not st.session_state.get("user") or not _ok:
    st.error("Accesso non autorizzato."); st.stop()

# Validation belongs to the review contract and its single confirmation.
# Do not intercept submits using stale checkbox session keys.
runpy.run_path("pages/_05_Scarico_Sala_AI_impl.py", run_name="__main__")
