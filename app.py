import streamlit as st

# OrthoFlow Control Tower router.
# The former monolithic app is preserved in core_app.py and remains the
# authenticated operational module. Navigation is grouped and role-aware.

logged_in = bool(st.session_state.get("user"))
role = str(st.session_state.get("ruolo", "")).strip()

login_page = st.Page(
    "pages/99_Login.py",
    title="OrthoFlow Control Tower",
    icon="🏥",
    url_path="login",
    default=not logged_in,
)

control_tower = st.Page(
    "pages/00_Control_Tower.py",
    title="Control Tower",
    icon="🛰️",
    url_path="control-tower",
    default=logged_in,
)

scarico_sala_ai_page = st.Page(
    "pages/05_Scarico_Sala_AI.py",
    title="Scarico Sala AI",
    icon="📸",
    url_path="scarico-sala-ai",
)

interventions_page = st.Page(
    "pages/06_Gestione_Interventi.py",
    title="Gestione Interventi",
    icon="💶",
    url_path="gestione-interventi",
)

work_implant_page = st.Page(
    "pages/07_Work_Implant.py",
    title="Work Implant",
    icon="📄",
    url_path="work-implant",
)

wms_page = st.Page(
    "pages/01_WMS.py",
    title="Scanner & WMS",
    icon="📦",
    url_path="wms",
)
qr_page = st.Page(
    "pages/02_QR_Scaffali.py",
    title="QR Scaffali",
    icon="🏷️",
    url_path="qr-scaffali",
)
shelf_page = st.Page(
    "pages/03_Gestione_Scaffale.py",
    title="Gestione Scaffale",
    icon="📚",
    url_path="gestione-scaffale",
)
ddt_mobile_page = st.Page(
    "pages/04_DDT_Carico_v2.py",
    title="DDT Carico Mobile",
    icon="🚚",
    url_path="ddt-carico-mobile",
)
operations_page = st.Page(
    "core_app.py",
    title="Gestionale",
    icon="🏥",
    url_path="gestionale",
)

if not logged_in:
    nav = st.navigation([login_page], position="hidden")
else:
    pages = {
        "HOME": [control_tower],
        "OPERATIVITÀ": [operations_page, scarico_sala_ai_page],
    }
    if role in {"Admin", "Amministrazione"}:
        pages["AMMINISTRAZIONE"] = [interventions_page, work_implant_page]
    if role in {"Admin", "Magazzino"}:
        pages["LOGISTICA & MAGAZZINO"] = [ddt_mobile_page, wms_page, shelf_page, qr_page]
    nav = st.navigation(pages, position="sidebar", expanded=True)

nav.run()
