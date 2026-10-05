import runpy

import streamlit as st

# OrthoFlow permission gate
_p=set(st.session_state.get("permessi",[]) or [])
_director=str(st.session_state.get("ruolo",""))=="Admin" or "DIREZIONE" in _p
_ok=_director or bool(_p & {'AMMINISTRAZIONE','LOGISTICA'})
if not st.session_state.get("user") or not _ok:
    st.error("Accesso non autorizzato."); st.stop()
from streamlit.delta_generator import DeltaGenerator

# Compatibility wrapper for the legacy monolithic Gestionale.
# The original implementation is preserved unchanged in core_app_legacy.py.
# Legacy entries are redirected to the dedicated modern pages.

SCARICO_AI_PAGE = "pages/05_Scarico_Sala_AI.py"
WORK_IMPLANT_PAGE = "pages/07_Work_Implant.py"
CUSTOMER_CONNECT_PAGE = "pages/08_Customer_Connect.py"
DDT_PAGE = "pages/04_DDT_Carico_v2.py"
DEDICATED_MENU = {"Scarico sala", "Work Implant", "Customer Connect", "DDT carico / Loan"}


def _legacy_options(options):
    if _director:
        return [entry for entry in options if entry not in DEDICATED_MENU]
    # Multi-function users are driven by assigned permissions, independently
    # of their primary role. This list never includes Director data tools.
    entries=[]
    if 'LOGISTICA' in _p:
        entries += ['Inventario']
    if 'AMMINISTRAZIONE' in _p:
        entries += ['Clienti','Offerte','Archivio impianti','KPI e Fatturato']
    return entries

# Handles legacy Dashboard quick-actions, which store the destination in
# session_state and rerun before the legacy menu is rendered.
quick_menu = st.session_state.get("quick_menu")
if quick_menu == "Scarico sala":
    st.session_state.pop("quick_menu", None)
    st.switch_page(SCARICO_AI_PAGE)
    st.stop()
if quick_menu == "Work Implant":
    st.session_state.pop("quick_menu", None)
    st.switch_page(WORK_IMPLANT_PAGE)
    st.stop()
if quick_menu == "Customer Connect":
    st.session_state.pop("quick_menu", None)
    st.switch_page(CUSTOMER_CONNECT_PAGE)
    st.stop()

if quick_menu == "DDT carico / Loan":
    st.session_state.pop("quick_menu", None)
    st.switch_page(DDT_PAGE)
    st.stop()

_original_button = DeltaGenerator.button


def _office_button(self, label, *args, **kwargs):
    pressed = _original_button(self, label, *args, **kwargs)
    if pressed and str(label).strip() == 'Esci' and st.session_state.get('office_runtime'):
        from mobile.access import COOKIE, session_file
        from mobile.security import Sessions
        Sessions(session_file()).revoke(st.context.cookies.get(COOKIE, ''))
        st.session_state.clear()
        st.info('Accesso terminato. Torna alla schermata principale dell’app.')
        st.stop()
    return pressed


if st.session_state.get('office_runtime'):
    DeltaGenerator.button = _office_button

_original_radio = DeltaGenerator.radio


def _route_legacy_menu(value):
    selected = str(value).strip()
    if selected == "DDT carico / Loan":
        st.switch_page(DDT_PAGE)
        st.stop()
    if selected == "Scarico sala":
        st.switch_page(SCARICO_AI_PAGE)
        st.stop()
    if selected == "Work Implant":
        st.switch_page(WORK_IMPLANT_PAGE)
        st.stop()
    if selected == "Customer Connect":
        st.switch_page(CUSTOMER_CONNECT_PAGE)
        st.stop()


def _orthoflow_radio(self, label, *args, **kwargs):
    if str(label).strip() == "Menu" and args:
        args = (_legacy_options(args[0]), *args[1:])
    value = _original_radio(self, label, *args, **kwargs)
    if str(label).strip() == "Menu":
        _route_legacy_menu(value)
    return value


DeltaGenerator.radio = _orthoflow_radio

_radio_mixin = None
_original_mixin_radio = None
try:
    from streamlit.elements.widgets.radio import RadioMixin
    _radio_mixin = RadioMixin
    _original_mixin_radio = RadioMixin.radio

    def _orthoflow_mixin_radio(self, label, *args, **kwargs):
        if str(label).strip() == "Menu" and args:
            args = (_legacy_options(args[0]), *args[1:])
        value = _original_mixin_radio(self, label, *args, **kwargs)
        if str(label).strip() == "Menu":
            _route_legacy_menu(value)
        return value

    RadioMixin.radio = _orthoflow_mixin_radio
except Exception:
    pass

try:
    runpy.run_path("core_app_legacy.py", run_name="__main__")
finally:
    DeltaGenerator.radio = _original_radio
    DeltaGenerator.button = _original_button
    if _radio_mixin is not None and _original_mixin_radio is not None:
        _radio_mixin.radio = _original_mixin_radio
