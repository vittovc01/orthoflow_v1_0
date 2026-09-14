import runpy

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

# Compatibility wrapper for the legacy monolithic Gestionale.
# The original implementation is preserved unchanged in core_app_legacy.py.
# Legacy entries are redirected to the dedicated modern pages.

SCARICO_AI_PAGE = "pages/05_Scarico_Sala_AI.py"
WORK_IMPLANT_PAGE = "pages/07_Work_Implant.py"
CUSTOMER_CONNECT_PAGE = "pages/08_Customer_Connect.py"

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

_original_radio = DeltaGenerator.radio


def _route_legacy_menu(value):
    selected = str(value).strip()
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
    if _radio_mixin is not None and _original_mixin_radio is not None:
        _radio_mixin.radio = _original_mixin_radio
