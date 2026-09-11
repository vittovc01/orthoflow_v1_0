import runpy

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

# Compatibility wrapper for the legacy monolithic Gestionale.
# The original implementation is preserved unchanged in core_app_legacy.py.
# When the user selects "Scarico sala" from the legacy Gestionale menu,
# route directly to the new camera/PDF + AI workflow.

_original_radio = DeltaGenerator.radio


def _orthoflow_radio(self, label, *args, **kwargs):
    value = _original_radio(self, label, *args, **kwargs)
    if str(label).strip() == "Menu" and value == "Scarico sala":
        st.switch_page("pages/05_Scarico_Sala_AI.py")
    return value


DeltaGenerator.radio = _orthoflow_radio
try:
    runpy.run_path("core_app_legacy.py", run_name="__main__")
finally:
    DeltaGenerator.radio = _original_radio
