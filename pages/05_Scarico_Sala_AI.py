import runpy
import streamlit as st

# Wrapper UX: evita il dead-lock del pulsante dentro st.form.
# In Streamlit i checkbox dentro un form non causano rerun immediato;
# quindi un submit disabilitato in base al checkbox può restare grigio per sempre.

_original_checkbox = st.checkbox
_original_submit = st.form_submit_button


def _checkbox(label, *args, **kwargs):
    if str(label).strip() == "Ho verificato codice Johnson/REF, lotto, scadenza e quantità di tutte le righe.":
        kwargs.setdefault("key", "scarico_verified")
    return _original_checkbox(label, *args, **kwargs)


def _submit(label, *args, **kwargs):
    if str(label).strip() == "📤 Crea intervento e scarica materiali":
        # Il pulsante deve essere sempre cliccabile: i controlli vengono fatti al click,
        # così l'utente riceve un messaggio esplicito invece di un bottone grigio senza spiegazioni.
        kwargs["disabled"] = False
        clicked = _original_submit(label, *args, **kwargs)
        if clicked:
            rows = st.session_state.get("scarico_ai_rows", []) or []
            if not rows:
                st.error("Manca la lista materiali. Analizza una foto/PDF oppure aggiungi almeno una riga prima di scaricare.")
                return False
            if not bool(st.session_state.get("scarico_verified", False)):
                st.warning("Spunta la verifica di codici, lotti, scadenze e quantità prima di creare l'intervento.")
                return False
        return clicked
    return _original_submit(label, *args, **kwargs)


st.checkbox = _checkbox
st.form_submit_button = _submit
try:
    runpy.run_path("pages/_05_Scarico_Sala_AI_impl.py", run_name="__main__")
finally:
    st.checkbox = _original_checkbox
    st.form_submit_button = _original_submit
