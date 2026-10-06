"""Shared P.M. Medical Control Tower identity for every operational page."""
from pathlib import Path

import streamlit as st

_ASSETS = Path(__file__).resolve().parent / "assets"
_ICON = _ASSETS / "pm-medical-icon.png"
_LOGO = _ASSETS / "pm-medical-logo.svg"

# Hide only hosting actions: the toolbar also contains the mobile menu toggle.
_HOSTING_CSS = """
<style>
[data-testid="stToolbarActions"],
.stToolbarActions,
[data-testid="stAppDeployButton"],
.stAppDeployButton,
[data-testid="stMainMenu"],
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
    title = kwargs.get("page_title", "P.M. Medical Control Tower")
    if "P.M. Medical" in title and "Control Tower" not in title:
        title = title.replace("P.M. Medical", "P.M. Medical Control Tower")
    kwargs["page_title"] = title
    kwargs["page_icon"] = str(_ICON)
    st.set_page_config(*args, **kwargs)
    st.logo(str(_LOGO), icon_image=str(_ICON), size="large")
    st.markdown(_HOSTING_CSS, unsafe_allow_html=True)
