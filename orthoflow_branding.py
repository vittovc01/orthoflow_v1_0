"""Shared OrthoFlow identity for every operational page."""
from pathlib import Path

import streamlit as st

_ASSETS = Path(__file__).resolve().parent / "assets"
_ICON = _ASSETS / "orthoflow-icon.png"
_LOGO = _ASSETS / "orthoflow-logo.svg"

# Hide hosting controls, while keeping the header and sidebar toggle usable.
_HOSTING_CSS = """
<style>
[data-testid="stToolbar"],
.stAppToolbar,
#MainMenu,
[data-testid="stAppViewerBadge"],
[data-testid="stViewerBadge"],
[class*="viewerBadge_container"],
[class*="viewerBadge_link"] {
    display: none !important;
}
</style>
"""


def configure_page(*args, **kwargs):
    """Keep each page's layout/title and apply the same product branding."""
    kwargs["page_icon"] = str(_ICON)
    st.set_page_config(*args, **kwargs)
    st.logo(str(_LOGO), icon_image=str(_ICON))
    st.markdown(_HOSTING_CSS, unsafe_allow_html=True)
