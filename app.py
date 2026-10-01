import streamlit as st

# OrthoFlow Control Tower router.
# The former monolithic app is preserved in core_app.py and remains the
# authenticated operational module. Navigation is grouped and role-aware.

logged_in = bool(st.session_state.get("user"))
role = str(st.session_state.get("ruolo", "")).strip()
permissions = set(st.session_state.get("permessi", []) or [])
is_director = role == "Admin" or "DIREZIONE" in permissions

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

customer_connect_page = st.Page(
    "pages/08_Customer_Connect.py",
    title="Customer Connect",
    icon="🔁",
    url_path="customer-connect",
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
courier_page = st.Page("pages/09_Corrieri.py", title="Corrieri", icon="🚐", url_path="corrieri")
documents_page = st.Page("pages/10_Documenti_Logistica.py", title="Documenti Logistica", icon="📑", url_path="documenti-logistica")
jj_orders_page = st.Page("pages/13_Controllo_Ordini_JJ.py", title="Controllo Ordini J&J", icon="🔎", url_path="controllo-ordini-jj")

users_page = st.Page("pages/11_Gestione_Utenti.py", title="Utenti & Permessi", icon="👥", url_path="utenti-permessi")
courier_data_page = st.Page("pages/12_Gestione_Dati_Corrieri.py", title="Gestione Dati Corrieri", icon="🗂️", url_path="gestione-dati-corrieri")
price_anomalies_page = st.Page("pages/14_Anomalie_Prezzi.py", title="Anomalie Prezzi", icon="⚠️", url_path="anomalie-prezzi")

operations_page = st.Page(
    "core_app.py",
    title="Gestionale",
    icon="🏥",
    url_path="gestionale",
)

if not logged_in:
    nav = st.navigation([login_page], position="hidden")
else:
    pages = {"HOME": [control_tower]}
    if is_director or "OPERATIVITA" in permissions:
        pages["OPERATIVITÀ"] = [operations_page, scarico_sala_ai_page]
    elif "AGENTE" in permissions:
        pages["OPERATIVITÀ"] = [scarico_sala_ai_page, customer_connect_page]
    if is_director or "AMMINISTRAZIONE" in permissions:
        pages["AMMINISTRAZIONE"] = [interventions_page, work_implant_page, customer_connect_page, jj_orders_page]
    if is_director or "LOGISTICA" in permissions:
        pages["LOGISTICA & MAGAZZINO"] = [ddt_mobile_page, wms_page, shelf_page, qr_page, courier_page, documents_page]
    elif "CORRIERE" in permissions:
        pages["CORRIERI"] = [courier_page]
    if is_director:
        pages["DIREZIONE"] = [operations_page, price_anomalies_page, users_page, courier_data_page]
    nav = st.navigation(pages, position="sidebar", expanded=True)

nav.run()
