import runpy

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

# Compatibility wrapper for the legacy monolithic Gestionale.
# The original implementation is preserved unchanged in core_app_legacy.py.
# Every legacy entry point named "Scarico sala" is redirected to the new
# camera/PDF + AI workflow.

SCARICO_AI_PAGE = "pages/05_Scarico_Sala_AI.py"

# Handles the legacy Dashboard quick-action, which stores the destination in
# session_state and reruns before the legacy menu is rendered.
if st.session_state.get("quick_menu") == "Scarico sala":
    st.session_state.pop("quick_menu", None)
    st.switch_page(SCARICO_AI_PAGE)
    st.stop()

_original_radio = DeltaGenerator.radio


def _orthoflow_radio(self, label, *args, **kwargs):
    value = _original_radio(self, label, *args, **kwargs)
    if str(label).strip() == "Menu" and str(value).strip() == "Scarico sala":
        st.switch_page(SCARICO_AI_PAGE)
        st.stop()
    return value


# Patch the DeltaGenerator method used by st.sidebar.radio.
DeltaGenerator.radio = _orthoflow_radio

# Some Streamlit releases resolve radio through RadioMixin directly; patch it
# too so the redirect behaves consistently after deploys/upgrades.
_radio_mixin = None
_original_mixin_radio = None
try:
    from streamlit.elements.widgets.radio import RadioMixin
    _radio_mixin = RadioMixin
    _original_mixin_radio = RadioMixin.radio

    def _orthoflow_mixin_radio(self, label, *args, **kwargs):
        value = _original_mixin_radio(self, label, *args, **kwargs)
        if str(label).strip() == "Menu" and str(value).strip() == "Scarico sala":
            st.switch_page(SCARICO_AI_PAGE)
            st.stop()
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
