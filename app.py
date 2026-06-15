
import streamlit as st
import pandas as pd
from datetime import date
from database import init_db, get_conn
from helpers import *
from ai_ocr import ai_enabled, analyze_image, normalize_ai_items, ocr_engine_status
import json

st.set_page_config(page_title="OrthoFlow Control Tower v1.1", page_icon="🦴", layout="wide", initial_sidebar_state="expanded")
init_db()

def ensure_alias_table():
    c = get_conn()
    c.execute("""CREATE TABLE IF NOT EXISTS alias_strutture(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        alias TEXT UNIQUE NOT NULL,
        codice_cliente TEXT NOT NULL,
        descrizione_cliente TEXT,
        priorita INTEGER DEFAULT 100,
        note TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    c.commit()
    c.close()

ensure_alias_table()


st.markdown("""
<style>
.block-container {padding-top: 1.2rem;}
.big-hero {
    background: linear-gradient(135deg,#064e3b,#10b981);
    color:white; padding:28px; border-radius:24px;
    box-shadow:0 10px 30px rgba(6,78,59,.18);
    margin-bottom:20px;
}
.big-hero h1 {font-size:40px;margin:0;}
.big-hero p {font-size:18px;margin:8px 0 0 0;opacity:.95;}
.quick-card {
    background:#ffffff;border:1px solid #e5e7eb;border-radius:18px;
    padding:18px;box-shadow:0 5px 18px rgba(0,0,0,.05);
}
.stButton>button {border-radius:14px;font-weight:700;}
</style>
""", unsafe_allow_html=True)



st.markdown("""
<style>
.block-container {padding-top: 1.5rem; padding-bottom: 2rem;}
section[data-testid="stSidebar"] {background: linear-gradient(180deg,#effff5 0%,#ffffff 100%);} 
.hero {background: linear-gradient(135deg,#0f5132 0%,#198754 55%,#69d89b 100%); padding: 28px 32px; border-radius: 24px; color: white; margin-bottom: 22px; box-shadow: 0 10px 28px rgba(16,81,50,.18);} 
.hero h1 {font-size: 42px; margin-bottom: 6px;} .hero p {font-size: 18px; opacity:.94;}
.soft-card {background:#fff; border:1px solid #eef2f0; border-radius:18px; padding:18px; box-shadow:0 4px 16px rgba(16,24,40,.05); margin-bottom:16px;}
.danger-box {border:1px solid #ffd5d5; background:#fff7f7; padding:16px; border-radius:16px; margin: 10px 0;}
.ok-box {border:1px solid #ccebd9; background:#f1fff6; padding:16px; border-radius:16px; margin: 10px 0;}
div[data-testid="stMetric"] {background:white; padding:16px; border-radius:18px; box-shadow:0 4px 16px rgba(16,24,40,.05);}
</style>
""", unsafe_allow_html=True)


def q(sql, params=()):
    c = get_conn()
    df = pd.read_sql_query(sql, c, params=params)
    c.close()
    return df


def is_admin():
    return st.session_state.get("ruolo") == "Admin"

def admin_only():
    if not is_admin():
        st.error("Accesso riservato all'amministratore.")
        st.stop()

def mobile_photo_uploader(label, key):
    st.markdown("### 📷 Scatta o carica una foto")
    st.caption("Da telefono puoi scegliere Fotocamera e scattare direttamente la foto.")
    return st.file_uploader(label, type=["jpg","jpeg","png","pdf"], key=key, accept_multiple_files=False)

def simple_step(title, text):
    st.markdown(f"""
    <div style="background:#f1fff6;border:1px solid #d7f2e2;border-radius:18px;padding:16px;margin:8px 0;">
      <b>{title}</b><br>{text}
    </div>
    """, unsafe_allow_html=True)



def exec_sql(sql, params=()):
    c = get_conn()
    c.execute(sql, params)
    c.commit()
    c.close()

def ensure_editable_schema():
    c = get_conn()
    tables = ["clienti","magazzino","offerte_header","interventi","righe_intervento","ddt","order_history","order_details","chiusure","anomalie"]
    for t in tables:
        try:
            cols = [r["name"] for r in c.execute(f"PRAGMA table_info({t})").fetchall()]
            if "stato_record" not in cols:
                c.execute(f"ALTER TABLE {t} ADD COLUMN stato_record TEXT DEFAULT 'Attivo'")
        except Exception:
            pass
    c.execute("""CREATE TABLE IF NOT EXISTS audit_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        utente TEXT,
        azione TEXT,
        tabella TEXT,
        riferimento TEXT,
        dettagli TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    c.commit(); c.close()

def log_action(azione, tabella, riferimento, dettagli=""):
    try:
        c = get_conn()
        c.execute("INSERT INTO audit_log(utente,azione,tabella,riferimento,dettagli) VALUES(?,?,?,?,?)",
                  (st.session_state.get("user",""), azione, tabella, str(riferimento), str(dettagli)))
        c.commit(); c.close()
    except Exception:
        pass

def editable_manager(table, title, columns=None):
    st.subheader(title)
    try:
        df = q(f"SELECT * FROM {table} ORDER BY id DESC")
    except Exception as e:
        st.error(f"Impossibile leggere {table}: {e}")
        return
    if df.empty:
        st.info("Nessun record presente.")
        return
    st.dataframe(df, use_container_width=True)
    ids = df["id"].astype(str).tolist() if "id" in df.columns else []
    if not ids:
        return
    sel = st.selectbox("Record da modificare/eliminare", ids, key=f"{table}_sel")
    row = df[df["id"].astype(str)==sel].iloc[0].to_dict()
    tab1, tab2 = st.tabs(["✏️ Modifica", "🗑️ Elimina/Annulla"])
    edit_cols = columns or [c for c in df.columns if c not in ["id","created_at"]]
    with tab1:
        with st.form(f"form_{table}"):
            values = {}
            for col in edit_cols:
                val = row.get(col, "")
                values[col] = st.text_input(col, "" if pd.isna(val) else str(val))
            ok = st.form_submit_button("Salva modifiche", use_container_width=True)
        if ok:
            c = get_conn()
            set_clause = ", ".join([f"{col}=?" for col in values])
            c.execute(f"UPDATE {table} SET {set_clause} WHERE id=?", list(values.values())+[sel])
            c.commit(); c.close()
            log_action("MODIFICA", table, sel, values)
            st.success("Modifiche salvate.")
            st.rerun()
    with tab2:
        st.markdown('<div class="danger-box">Eliminazione sicura: il record viene marcato come Annullato quando possibile, così resta tracciabile.</div>', unsafe_allow_html=True)
        if st.button("Annulla / elimina record selezionato", type="primary", use_container_width=True, key=f"del_{table}"):
            cols = list(df.columns)
            c = get_conn()
            if "stato_record" in cols:
                c.execute(f"UPDATE {table} SET stato_record='Annullato' WHERE id=?", (sel,))
            else:
                c.execute(f"DELETE FROM {table} WHERE id=?", (sel,))
            c.commit(); c.close()
            log_action("ANNULLA/ELIMINA", table, sel)
            st.success("Record annullato/eliminato.")
            st.rerun()

ensure_editable_schema()

def login():
    st.sidebar.markdown("## 🦴 OrthoFlow")
    st.sidebar.caption("Control Tower Magazzino")
    if "user" not in st.session_state:
        with st.sidebar.form("login"):
            u = st.text_input("Utente", "admin")
            p = st.text_input("Password", "admin", type="password")
            ok = st.form_submit_button("Accedi")
        if ok:
            c = get_conn()
            r = c.execute("SELECT * FROM utenti WHERE username=? AND password=?", (u,p)).fetchone()
            c.close()
            if r:
                st.session_state.user = u
                st.session_state.ruolo = r["ruolo"]
                st.rerun()
            st.sidebar.error("Credenziali errate")
        st.markdown("""<div class="hero"><h1>OrthoFlow</h1><p>La web app per governare DDT, magazzino, scarichi sala, Loan, Work Implant e Customer Connect.</p></div>""", unsafe_allow_html=True)
        st.info("Accesso demo: admin / admin")
        return False
    st.sidebar.success(st.session_state.user)
    if st.sidebar.button("Esci"):
        st.session_state.clear()
        st.rerun()
    return True

if not login():
    st.stop()


ruolo = st.session_state.get("ruolo", "Agente")

admin_menu = [
    "🏠 Home",
    "📸 Nuovo scarico sala",
    "🚚 Nuovo DDT / Loan",
    "📄 Work Implant",
    "🔁 Customer Connect",
    "👥 Clienti",
    "🏷️ Alias strutture",
    "📦 Magazzino",
    "💰 Offerte",
    "📊 Fatturato e KPI",
    "⏳ Loan Monitor",
    "🗓️ Scadenze",
    "🧾 Ordini e chiusure",
    "🔍 Riconciliazione",
    "⚠️ Anomalie",
    "🛠️ Gestione dati",
    "📤 Export completo"
]

collaboratore_menu = [
    "🏠 Home",
    "📸 Nuovo scarico sala"
]

_menu_list = admin_menu if ruolo == "Admin" else collaboratore_menu
_default_index = 0
if st.session_state.get("_quick_nav") in _menu_list:
    _default_index = _menu_list.index(st.session_state.pop("_quick_nav"))
menu = st.sidebar.radio("Menu", _menu_list, index=_default_index)



if menu == "🏠 Home":
    st.markdown("""
    <div class="big-hero">
      <h1>🦴 OrthoFlow</h1>
      <p>Carica foto, controlla le righe, conferma. Il resto lo fa l'app.</p>
    </div>
    """, unsafe_allow_html=True)

    st.subheader("Azioni rapide")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="quick-card"><h3>📸 Scarico sala</h3><p>Foto etichette sala operatoria → Work Implant → Customer Connect.</p></div>', unsafe_allow_html=True)
    with c2:
        st.markdown('<div class="quick-card"><h3>🚚 DDT / Loan</h3><p>Foto DDT Johnson → carico magazzino o Loan conto visione.</p></div>', unsafe_allow_html=True)

    st.subheader("Istruzioni per collaboratori")
    simple_step("1. Scatta la foto", "Apri dal telefono e carica una foto chiara del documento.")
    simple_step("2. Controlla la tabella", "Verifica codice, lotto, scadenza, quantità e produttore.")
    simple_step("3. Conferma", "L'app genera Work Implant e, se previsto, il reintegro Customer Connect.")

    if is_admin():
        st.info("Accesso Admin attivo: puoi gestire anagrafiche, offerte, fatturato, KPI e dati.")
    else:
        st.success("Accesso Collaboratore: visualizzi solo le funzioni operative.")

elif menu == "📸 Nuovo scarico sala":
    st.title("📸 Nuovo scarico sala con riconoscimento struttura")
    st.info("Scatta/carica una foto. L'AI legge la struttura, l'app la collega al cliente e poi valorizza con l'offerta corretta.")

    clienti_df = q("SELECT codice_cliente, descrizione FROM clienti ORDER BY descrizione")
    agenti = q("SELECT nome FROM agenti ORDER BY nome")["nome"].tolist()
    allegato = st.file_uploader("Foto scarico sala", type=["jpg","jpeg","png","pdf"], key="scarico_v14")
    saved_path = ""
    ai_meta = st.session_state.get("ai_scarico_meta_v14", {})
    ai_rows = st.session_state.get("ai_scarico_rows_v14", [])

    if allegato:
        saved_path = save_file(allegato)
        if getattr(allegato, "type", "").startswith("image/"):
            st.image(allegato, caption="Foto scarico sala", use_container_width=True)
            if st.button("Estrai codici / lotti / scadenze"):
                if not ai_enabled():
                    st.error("OCR non configurato. Il gratuito usa ENABLE_FREE_OCR=true; l'AI avanzata usa OPENAI_API_KEY.")
                else:
                    with st.spinner("Lettura AI in corso..."):
                        try:
                            ai_meta = analyze_image(saved_path, mode="scarico_sala")
                            ai_rows = normalize_ai_items(ai_meta)
                            st.session_state["ai_scarico_meta_v14"] = ai_meta
                            st.session_state["ai_scarico_rows_v14"] = ai_rows
                            st.success(f"Righe lette: {len(ai_rows)}")
                        except Exception as e:
                            st.error(f"Errore AI OCR: {e}")

    detected_clinic = (ai_meta or {}).get("clinic_name") or ""
    resolved = None
    if detected_clinic:
        c = get_conn()
        resolved = resolve_cliente_from_structure(c, detected_clinic)
        c.close()
        if resolved:
            st.success(f"Struttura letta: {detected_clinic} → Cliente {resolved['codice_cliente']} - {resolved['descrizione']} ({resolved['metodo']}, score {resolved['score']})")
        else:
            st.warning(f"Struttura letta: {detected_clinic}, ma non collegata. Aggiungi alias o seleziona manualmente.")

    
    st.subheader("Diagnostica OCR / Aggancio")
    diag_cols = st.columns(4)
    diag_cols[0].metric("Motore OCR", ocr_engine_status())
    diag_cols[1].metric("Struttura letta", detected_clinic if detected_clinic else "NON LETTA")
    diag_cols[2].metric("Cliente agganciato", resolved["codice_cliente"] if resolved else "NO")
    diag_cols[3].metric("Righe estratte", len(ai_rows) if ai_rows else 0)

    if ai_meta:
        with st.expander("Vedi risultato OCR completo"):
            st.json(ai_meta)

if ai_rows:
        st.subheader("Righe estratte - correggi prima di salvare")
        edited = st.data_editor(pd.DataFrame(ai_rows), use_container_width=True, num_rows="dynamic", key="editor_ai_scarico_v34")
    else:
        edited = pd.DataFrame(columns=["codice","descrizione","lotto","scadenza","quantita","produttore","is_jnj"])

    with st.form("salva_scarico_v14"):
        data_int = st.date_input("Data intervento", date.today())
        labels = [f"{r.codice_cliente} - {r.descrizione}" for r in clienti_df.itertuples()]
        default_idx = 0
        if resolved and labels:
            for i, lab in enumerate(labels):
                if lab.startswith(str(resolved["codice_cliente"]) + " - "):
                    default_idx = i
                    break
        cliente_label = st.selectbox("Cliente/struttura riconosciuta", labels if labels else [""], index=default_idx if labels else 0)
        codice_cliente = cliente_label.split(" - ")[0] if cliente_label else ""
        cliente = " - ".join(cliente_label.split(" - ")[1:]) if " - " in cliente_label else cliente_label
        cartella = st.text_input("Cartella clinica", value=(ai_meta or {}).get("clinical_record") or "")
        agente = st.selectbox("Agente", agenti if agenti else [""])
        linea = st.selectbox("Linea", ["TRAUMA", "PROTESICA", "CMF", "SPINE", "SPORTS", "ALTRO"])
        chirurgo = st.text_input("Chirurgo", value=(ai_meta or {}).get("surgeon") or "")
        note = st.text_area("Note")
        ok = st.form_submit_button("Salva scarico e calcola fatturato")
    if ok:
        c = get_conn()
        cur = c.execute("""INSERT INTO interventi(data_intervento,codice_cliente,cliente,cartella_clinica,agente,chirurgo,linea,allegato,note,stato_record)
                           VALUES(?,?,?,?,?,?,?,?,?,'Attivo')""", (str(data_int),codice_cliente,cliente,cartella,agente,chirurgo,linea,saved_path,note))
        iid = cur.lastrowid
        imported = 0
        for _, rr in edited.iterrows():
            codice = str(rr.get("codice","")).strip()
            lotto = str(rr.get("lotto","")).strip()
            if not codice or codice.lower()=="nan":
                continue
            qta = money(rr.get("quantita")) or 1
            prod = str(rr.get("produttore",""))
            valid = validate_produttore(prod)
            if "is_jnj" in rr and bool(rr.get("is_jnj")) is False:
                valid = "Prodotto non J&J"
            origine = detect_origine(c, codice, lotto)
            prezzo = prezzo_per(c, codice_cliente, codice, linea, str(data_int))
            totale = prezzo*qta if prezzo is not None else None
            reintegro = 0 if origine == "LOAN / CONTO VISIONE" else 1
            c.execute("""INSERT INTO righe_intervento(intervento_id,codice,descrizione,lotto,scadenza,quantita,produttore,validazione,origine,prezzo,totale,reintegro,stato_record)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?, 'Attivo')""", (iid,codice,str(rr.get("descrizione","")),lotto,str(rr.get("scadenza","")),qta,prod,valid,origine,prezzo,totale,reintegro))
            if prezzo is None and valid == "Validato J&J":
                issues = diagnose_price(c, codice_cliente, codice, linea, str(data_int))
                c.execute("INSERT INTO anomalie(tipo,gravita,descrizione) VALUES('Prezzo mancante','Media',?)",
                          (f"Intervento {iid}, cliente {codice_cliente}, linea {linea}, codice {codice}: " + "; ".join(issues),))
            imported += 1
        c.commit(); c.close()
        st.success(f"Scarico salvato. Intervento {iid}. Righe importate: {imported}")

elif menu == "🚚 Nuovo DDT / Loan":
    admin_only()
    st.title("🚚 Nuovo DDT / Loan")
    st.info("Carica o scatta una foto del DDT. Se è Loan/Conto Visione non verrà inserito nei reintegri.")
    st.warning("Usa il menu 'DDT carico / Loan' nella versione corrente se questa pagina non mostra il form completo dopo aggiornamento.")

if menu == "Dashboard":
    st.markdown("""<div class="hero"><h1>OrthoFlow Control Tower</h1><p>Dashboard operativa per collaboratori, agenti e amministrazione.</p></div>""", unsafe_allow_html=True)
    c = get_conn()
    metrics = {
        "Clienti": c.execute("SELECT COUNT(*) n FROM clienti WHERE COALESCE(stato_record,'Attivo')='Attivo'").fetchone()["n"],
        "Righe magazzino": c.execute("SELECT COUNT(*) n FROM magazzino WHERE COALESCE(stato_record,'Attivo')='Attivo'").fetchone()["n"],
        "Interventi": c.execute("SELECT COUNT(*) n FROM interventi WHERE COALESCE(stato_record,'Attivo')='Attivo'").fetchone()["n"],
        "Anomalie aperte": c.execute("SELECT COUNT(*) n FROM anomalie WHERE stato='Aperta'").fetchone()["n"],
        "Fatturato teorico": c.execute("SELECT COALESCE(SUM(totale),0) n FROM righe_intervento WHERE validazione='Validato J&J'").fetchone()["n"],
    }
    c.close()
    cols = st.columns(5)
    for col, (k,v) in zip(cols, metrics.items()):
        col.metric(k, f"€ {v:,.2f}" if k=="Fatturato teorico" else v)
    st.subheader("Fatturato per agente")
    st.dataframe(q("""SELECT i.agente, COUNT(DISTINCT i.id) interventi, COALESCE(SUM(r.totale),0) fatturato
                      FROM interventi i LEFT JOIN righe_intervento r ON r.intervento_id=i.id
                      GROUP BY i.agente ORDER BY fatturato DESC"""), use_container_width=True)


elif menu == "KPI Agenti":
    st.title("KPI Agenti")
    st.subheader("Fatturato e interventi per agente")
    df = q("""SELECT i.agente, COUNT(DISTINCT i.id) interventi,
              COUNT(r.id) righe,
              COALESCE(SUM(r.totale),0) fatturato_teorico,
              COALESCE(AVG(r.totale),0) valore_medio_riga
              FROM interventi i
              LEFT JOIN righe_intervento r ON r.intervento_id=i.id AND r.validazione='Validato J&J'
              GROUP BY i.agente
              ORDER BY fatturato_teorico DESC""")
    st.dataframe(df, use_container_width=True)
    if not df.empty:
        st.download_button("Scarica KPI agenti", excel_bytes({"KPI Agenti": df}), "kpi_agenti.xlsx")

    st.subheader("Dettaglio per agente e struttura")
    det = q("""SELECT i.agente, i.cliente, i.linea, COUNT(DISTINCT i.id) interventi,
               COALESCE(SUM(r.totale),0) fatturato
               FROM interventi i
               LEFT JOIN righe_intervento r ON r.intervento_id=i.id AND r.validazione='Validato J&J'
               GROUP BY i.agente, i.cliente, i.linea
               ORDER BY i.agente, fatturato DESC""")
    st.dataframe(det, use_container_width=True)

elif menu in ["Loan Monitor", "⏳ Loan Monitor"]:
    admin_only()
    st.title("Loan Monitor")
    st.write("Controlla materiale Loan / Conto Visione: entra nel WI, non entra nel reintegro.")
    df = q("""SELECT codice, descrizione, lotto, scadenza, quantita, origine
              FROM magazzino
              WHERE origine='LOAN / CONTO VISIONE'
              ORDER BY codice, lotto""")
    st.subheader("Loan presenti")
    st.dataframe(df, use_container_width=True)

    used = q("""SELECT i.data_intervento, i.cliente, i.cartella_clinica, i.agente,
                r.codice, r.lotto, r.quantita, r.totale
                FROM righe_intervento r
                JOIN interventi i ON i.id=r.intervento_id
                WHERE r.origine='LOAN / CONTO VISIONE'
                ORDER BY i.data_intervento DESC""")
    st.subheader("Loan utilizzati in sala")
    st.dataframe(used, use_container_width=True)

    if not df.empty or not used.empty:
        st.download_button("Scarica Loan Monitor", excel_bytes({"Loan presenti": df, "Loan utilizzati": used}), "loan_monitor.xlsx")

elif menu in ["Scadenze", "🗓️ Scadenze"]:
    st.title("Scadenze materiale")
    st.write("Vista scadenze da magazzino. Le date testuali non normalizzate potrebbero richiedere revisione.")
    df = q("""SELECT codice, descrizione, lotto, scadenza, quantita, origine
              FROM magazzino
              WHERE scadenza IS NOT NULL AND scadenza <> ''
              ORDER BY scadenza ASC""")
    st.dataframe(df, use_container_width=True)
    if not df.empty:
        st.download_button("Scarica scadenze", excel_bytes({"Scadenze": df}), "scadenze_magazzino.xlsx")

elif menu == "Import iniziali":
    admin_only()
    st.title("Import iniziali")
    tab1, tab2, tab3 = st.tabs(["Clienti",
    "🏷️ Alias strutture", "Magazzino", "Agenti"])
    with tab1:
        f = st.file_uploader("Anagrafica clienti Excel", type=["xlsx","xls"], key="clienti")
        if f:
            df = norm(pd.read_excel(f))
            st.write(f"Righe lette dal file: **{len(df)}**")
            st.dataframe(df, use_container_width=True)
            cols = list(df.columns)
            cc = st.selectbox("Codice cliente", cols)
            desc = st.selectbox("Descrizione", cols, index=cols.index("Descrizione") if "Descrizione" in cols else 0)
            city = st.selectbox("Città", [""]+cols)
            prov = st.selectbox("Provincia", [""]+cols)
            piva = st.selectbox("P.IVA", [""]+cols)
            if st.button("Importa clienti"):
                c = get_conn()
                for _, r in df.iterrows():
                    c.execute("""INSERT OR REPLACE INTO clienti(codice_cliente,descrizione,citta,provincia,piva)
                                 VALUES(?,?,?,?,?)""", (str(r[cc]), str(r[desc]), "" if not city else str(r[city]), "" if not prov else str(r[prov]), "" if not piva else str(r[piva])))
                c.commit(); c.close()
                log_action("IMPORT", "clienti", "excel", f"righe={len(df)}")
                st.success(f"Clienti importati/aggiornati: {len(df)}")
    with tab2:
        f = st.file_uploader("Giacenze magazzino Excel", type=["xlsx","xls"], key="mag")
        if f:
            df = norm(pd.read_excel(f))
            st.dataframe(df.head(20), use_container_width=True)
            cols = list(df.columns)
            cod = st.selectbox("Codice", cols)
            lot = st.selectbox("Lotto", cols)
            qty = st.selectbox("Quantità", cols)
            des = st.selectbox("Descrizione", [""]+cols)
            sca = st.selectbox("Scadenza", [""]+cols)
            ori = st.selectbox("Origine", ["CONTO DEPOSITO", "LOAN / CONTO VISIONE"])
            if st.button("Importa magazzino"):
                c = get_conn()
                n = 0
                for _, r in df.iterrows():
                    codice, lotto = str(r[cod]).strip(), str(r[lot]).strip()
                    if not codice or codice=="nan" or not lotto or lotto=="nan":
                        continue
                    qta = pd.to_numeric(r[qty], errors="coerce")
                    qta = 0 if pd.isna(qta) else float(qta)
                    c.execute("""INSERT OR REPLACE INTO magazzino(codice,descrizione,lotto,scadenza,quantita,origine)
                                 VALUES(?,?,?,?,?,?)""", (codice, "" if not des else str(r[des]), lotto, "" if not sca else str(r[sca]), qta, ori))
                    n += 1
                c.commit(); c.close()
                st.success(f"Importate {n} righe")
    with tab3:
        st.dataframe(q("SELECT * FROM agenti ORDER BY nome"), use_container_width=True)
        nome = st.text_input("Nuovo agente")
        if st.button("Aggiungi agente") and nome:
            c = get_conn(); c.execute("INSERT OR IGNORE INTO agenti(nome) VALUES(?)", (nome,)); c.commit(); c.close()
            st.success("Agente aggiunto")

elif menu in ["Offerte", "💰 Offerte"]:
    admin_only()
    st.title("Gestione offerte")
    st.write("Qui potrai aggiungere nuove offerte anche in futuro, senza modificare l'app.")
    tab1, tab2 = st.tabs(["Crea offerta", "Importa prezzi"])
    with tab1:
        with st.form("offerta"):
            nome = st.text_input("Nome offerta / gara")
            linea = st.selectbox("Linea", ["TRAUMA", "PROTESICA", "CMF", "SPINE", "SPORTS", "ALTRO"])
            di = st.text_input("Data inizio validità", "")
            dfine = st.text_input("Data fine validità", "")
            note = st.text_area("Note")
            clienti = st.text_area("Codici clienti associati, separati da virgola o a capo")
            ok = st.form_submit_button("Crea offerta")
        if ok:
            c = get_conn()
            cur = c.execute("INSERT INTO offerte_header(nome_offerta,linea,data_inizio,data_fine,note) VALUES(?,?,?,?,?)", (nome,linea,di,dfine,note))
            off_id = cur.lastrowid
            for x in clienti.replace(",", "\n").splitlines():
                x = x.strip()
                if x:
                    c.execute("INSERT INTO offerte_clienti(offerta_id,codice_cliente) VALUES(?,?)", (off_id, x))
            c.commit(); c.close()
            st.success(f"Offerta creata ID {off_id}")
    with tab2:
        offerte = q("SELECT id, nome_offerta, linea FROM offerte_header ORDER BY id DESC")
        if offerte.empty:
            st.info("Crea prima un'offerta.")
        else:
            sel = st.selectbox("Offerta", [f"{r.id} - {r.nome_offerta} ({r.linea})" for r in offerte.itertuples()])
            off_id = int(sel.split(" - ")[0])
            f = st.file_uploader("Excel prezzi offerta", type=["xlsx","xls"])
            if f:
                sheet = st.text_input("Nome foglio da leggere, lascia vuoto per il primo", "")
                df = norm(pd.read_excel(f, sheet_name=sheet if sheet else 0))
                st.dataframe(df.head(30), use_container_width=True)
                cols = list(df.columns)
                cod = st.selectbox("Codice prodotto", cols)
                pre = st.selectbox("Prezzo", cols)
                des = st.selectbox("Descrizione", [""]+cols)
                iva = st.selectbox("IVA", [""]+cols)
                cnd = st.selectbox("CND", [""]+cols)
                rdm = st.selectbox("RDM", [""]+cols)
                if st.button("Importa prezzi"):
                    c = get_conn()
                    n = 0
                    for _, r in df.iterrows():
                        prezzo = money(r[pre])
                        codice = str(r[cod]).strip()
                        if not codice or codice=="nan" or prezzo is None:
                            continue
                        c.execute("""INSERT INTO offerte_prezzi(offerta_id,codice,descrizione,prezzo,iva,cnd,rdm)
                                     VALUES(?,?,?,?,?,?,?)""", (off_id,codice,"" if not des else str(r[des]),prezzo,"" if not iva else str(r[iva]),"" if not cnd else str(r[cnd]),"" if not rdm else str(r[rdm])))
                        n += 1
                    c.commit(); c.close()
                    st.success(f"Prezzi importati: {n}")
    st.subheader("Offerte presenti")
    st.dataframe(q("""SELECT h.id, h.nome_offerta, h.linea, h.data_inizio, h.data_fine,
                      GROUP_CONCAT(c.codice_cliente) clienti
                      FROM offerte_header h LEFT JOIN offerte_clienti c ON c.offerta_id=h.id
                      GROUP BY h.id ORDER BY h.id DESC"""), use_container_width=True)

elif menu in ["DDT carico / Loan", "🚚 DDT carico / Loan", "🚚 Nuovo DDT / Loan"]:
    admin_only()
    st.title("DDT carico / Loan con OCR AI")
    st.write("I DDT 'Conto Visione / Loan' entrano nel WI se impiantati, ma NON nel reintegro Customer Connect.")

    allegato = st.file_uploader("Carica DDT foto/PDF", type=["pdf","jpg","jpeg","png"], key="ddt_ai_file")
    saved_path = ""
    ddt_ai = {}
    ddt_rows = []

    if allegato:
        saved_path = save_file(allegato)
        st.success(f"File salvato: {saved_path}")
        if allegato.type.startswith("image/"):
            st.image(allegato, caption="DDT", use_container_width=True)
            if st.button("Analizza DDT con OCR AI"):
                if not ai_enabled():
                    st.error("OCR non configurato. Il gratuito usa ENABLE_FREE_OCR=true; l'AI avanzata usa OPENAI_API_KEY.")
                else:
                    with st.spinner("Analisi DDT in corso..."):
                        try:
                            ddt_ai = analyze_image(saved_path, mode="ddt")
                            ddt_rows = normalize_ai_items(ddt_ai)
                            st.session_state["ai_ddt_meta"] = ddt_ai
                            st.session_state["ai_ddt_rows"] = ddt_rows
                            st.success(f"Righe DDT estratte: {len(ddt_rows)}")
                        except Exception as e:
                            st.error(f"Errore OCR AI: {e}")
        elif allegato.type == "application/pdf":
            text = pdf_text(allegato)
            st.text_area("Testo PDF estratto", text[:4000], height=180)
            st.info("Per DDT PDF nativi puoi usare i dati estratti testualmente; per scansioni/foto usa OCR AI su immagine.")

    meta = st.session_state.get("ai_ddt_meta", {}) or {}
    rows = st.session_state.get("ai_ddt_rows", []) or []
    if rows:
        st.subheader("Righe DDT estratte da verificare")
        edited = st.data_editor(pd.DataFrame(rows), use_container_width=True, num_rows="dynamic", key="editor_ai_ddt_v34")
    else:
        edited = pd.DataFrame(columns=["codice","descrizione","lotto","scadenza","quantita","produttore"])

    with st.form("ddt_ai_form"):
        numero = st.text_input("Numero DDT", value=meta.get("ddt_number") or "")
        data_ddt = st.text_input("Data DDT", value=meta.get("ddt_date") or str(date.today()))
        default_tipo = "LOAN / CONTO VISIONE" if meta.get("is_loan_or_conto_visione") else "CONTO DEPOSITO"
        tipo = st.selectbox("Tipo DDT", ["CONTO DEPOSITO", "LOAN / CONTO VISIONE"], index=0 if default_tipo=="CONTO DEPOSITO" else 1)
        cliente = st.text_input("Cliente/destinazione", value=meta.get("customer") or meta.get("destination") or "")
        note = st.text_area("Note", value=meta.get("transport_reason") or "")
        ok = st.form_submit_button("Crea DDT e carica righe in magazzino/loan")
    if ok:
        c = get_conn()
        cur = c.execute("INSERT INTO ddt(numero_ddt,data_ddt,tipo_ddt,cliente,allegato,note) VALUES(?,?,?,?,?,?)", (numero,str(data_ddt),tipo,cliente,saved_path,note))
        ddt_id = cur.lastrowid
        n = 0
        for _, rr in edited.iterrows():
            codice = str(rr.get("codice","")).strip()
            lotto = str(rr.get("lotto","")).strip()
            if not codice or not lotto or codice.lower()=="nan" or lotto.lower()=="nan":
                continue
            qta = money(rr.get("quantita")) or 1
            descr = str(rr.get("descrizione",""))
            scad = str(rr.get("scadenza",""))
            c.execute("""INSERT INTO ddt_righe(ddt_id,codice,descrizione,lotto,scadenza,quantita,origine)
                         VALUES(?,?,?,?,?,?,?)""", (ddt_id,codice,descr,lotto,scad,qta,tipo))
            c.execute("""INSERT INTO magazzino(codice,descrizione,lotto,scadenza,quantita,origine)
                         VALUES(?,?,?,?,?,?)
                         ON CONFLICT(codice,lotto,origine) DO UPDATE SET quantita=quantita+excluded.quantita, descrizione=excluded.descrizione, scadenza=excluded.scadenza""",
                      (codice,descr,lotto,scad,qta,tipo))
            n += 1
        c.commit(); c.close()
        st.success(f"DDT {ddt_id} creato. Righe caricate: {n}")
    st.subheader("DDT registrati")
    st.dataframe(q("SELECT * FROM ddt ORDER BY id DESC"), use_container_width=True)
elif menu in ["Scarico sala", "🏥 Scarico sala", "📸 Nuovo scarico sala"]:
    st.title("Scarico sala con OCR AI")
    clienti = q("SELECT codice_cliente || ' - ' || descrizione label FROM clienti ORDER BY descrizione")["label"].tolist()
    agenti = q("SELECT nome FROM agenti ORDER BY nome")["nome"].tolist()

    st.subheader("1) Carica foto/PDF scarico")
    allegato = st.file_uploader("Foto/PDF scarico sala", type=["pdf","jpg","jpeg","png"], key="scarico_ai_file")
    ai_rows = []
    ai_meta = {}
    saved_path = ""

    if allegato:
        saved_path = save_file(allegato)
        st.success(f"File salvato: {saved_path}")
        if allegato.type.startswith("image/"):
            st.image(allegato, caption="Scarico sala", use_container_width=True)
            if st.button("Estrai codici / lotti / scadenze"):
                if not ai_enabled():
                    st.error("OCR non configurato. Il gratuito usa ENABLE_FREE_OCR=true; l'AI avanzata usa OPENAI_API_KEY.")
                else:
                    with st.spinner("Analisi AI in corso..."):
                        try:
                            ai_meta = analyze_image(saved_path, mode="scarico_sala")
                            ai_rows = normalize_ai_items(ai_meta)
                            st.session_state["ai_scarico_meta"] = ai_meta
                            st.session_state["ai_scarico_rows"] = ai_rows
                            st.success(f"Righe estratte: {len(ai_rows)}")
                        except Exception as e:
                            st.error(f"Errore OCR AI: {e}")
        elif allegato.type == "application/pdf":
            text = pdf_text(allegato)
            st.text_area("Testo PDF estratto", text[:4000], height=180)
            st.info("Per PDF scansionati serve conversione pagine→immagini/OCR AI. In questa v0.6 l'OCR AI lavora direttamente sulle immagini caricate.")

    if "ai_scarico_rows" in st.session_state and st.session_state["ai_scarico_rows"]:
        st.subheader("2) Righe estratte da verificare")
        df_ai = pd.DataFrame(st.session_state["ai_scarico_rows"])
        edited = st.data_editor(df_ai, use_container_width=True, num_rows="dynamic", key="editor_ai_scarico_legacy_v34")
    else:
        edited = pd.DataFrame(columns=["codice","descrizione","lotto","scadenza","quantita","produttore","is_jnj","warning"])

    st.subheader("3) Crea intervento")
    with st.form("intervento_ai"):
        data_int = st.date_input("Data intervento", date.today())
        cliente_label = st.selectbox("Struttura", clienti if clienti else [""])
        codice_cliente = cliente_label.split(" - ")[0] if cliente_label else ""
        cliente = " - ".join(cliente_label.split(" - ")[1:]) if " - " in cliente_label else cliente_label
        cartella = st.text_input("Cartella clinica", value=(st.session_state.get("ai_scarico_meta", {}) or {}).get("clinical_record") or "")
        agente = st.selectbox("Agente", agenti)
        linea = st.selectbox("Linea", ["TRAUMA", "PROTESICA", "CMF", "SPINE", "SPORTS", "ALTRO"])
        chirurgo = st.text_input("Chirurgo", value=(st.session_state.get("ai_scarico_meta", {}) or {}).get("surgeon") or "")
        note = st.text_area("Note")
        crea = st.form_submit_button("Crea intervento e importa righe AI/manuali")

    if crea:
        c = get_conn()
        cur = c.execute("""INSERT INTO interventi(data_intervento,codice_cliente,cliente,cartella_clinica,agente,chirurgo,linea,allegato,note)
                           VALUES(?,?,?,?,?,?,?,?,?)""", (str(data_int),codice_cliente,cliente,cartella,agente,chirurgo,linea,saved_path,note))
        iid = cur.lastrowid

        imported = 0
        for _, rr in edited.iterrows():
            codice = str(rr.get("codice","")).strip()
            lotto = str(rr.get("lotto","")).strip()
            if not codice or codice.lower() == "nan":
                continue
            qta = money(rr.get("quantita")) or 1
            prod = str(rr.get("produttore",""))
            valid = validate_produttore(prod)
            # Se AI ha già escluso prodotto non J&J, mantieni esclusione anche se campo produttore è ambiguo
            if "is_jnj" in rr and bool(rr.get("is_jnj")) is False:
                valid = "Prodotto non J&J"
            origine = detect_origine(c, codice, lotto)
            prezzo = prezzo_per(c, codice_cliente, codice, linea, str(data_int))
            totale = prezzo*qta if prezzo is not None else None
            reintegro = 0 if origine == "LOAN / CONTO VISIONE" else 1
            c.execute("""INSERT INTO righe_intervento(intervento_id,codice,descrizione,lotto,scadenza,quantita,produttore,validazione,origine,prezzo,totale,reintegro)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (iid,codice,str(rr.get("descrizione","")),lotto,str(rr.get("scadenza","")),qta,prod,valid,origine,prezzo,totale,reintegro))
            if valid != "Validato J&J":
                c.execute("INSERT INTO anomalie(tipo,gravita,descrizione) VALUES('Prodotto non J&J / Marchio dubbio','Alta',?)", (f"Intervento {iid}: {codice} lotto {lotto} produttore {prod}. Escluso da WI J&J e reintegro.",))
            if origine == "LOAN / CONTO VISIONE":
                c.execute("INSERT INTO anomalie(tipo,gravita,descrizione) VALUES('Loan utilizzato','Alta',?)", (f"Intervento {iid}: {codice} lotto {lotto}. Entra nel WI ma NON nel reintegro.",))
            if prezzo is None and valid == "Validato J&J":
                c.execute("INSERT INTO anomalie(tipo,gravita,descrizione) VALUES('Prezzo mancante','Media',?)", (f"Cliente {codice_cliente}, linea {linea}, codice {codice}.",))
            if origine == "NON TROVATO" and valid == "Validato J&J":
                c.execute("INSERT INTO anomalie(tipo,gravita,descrizione) VALUES('Lotto non trovato','Alta',?)", (f"Intervento {iid}: {codice} + lotto {lotto} non presente in magazzino/loan.",))
            c.execute("UPDATE magazzino SET quantita=quantita-? WHERE codice=? AND lotto=? AND origine=?", (qta,codice,lotto,origine))
            imported += 1
        c.commit(); c.close()
        st.success(f"Intervento {iid} creato. Righe importate: {imported}")
elif menu in ["Work Implant", "📄 Work Implant"]:
    admin_only()
    st.title("Work Implant")
    df = q("""SELECT i.data_intervento Data, i.cliente Clinica, i.cartella_clinica Cartella, i.agente Agente, i.linea Linea,
              r.codice Codice, r.descrizione Descrizione, r.lotto Lotto, r.quantita Quantita,
              r.origine Origine, r.prezzo Prezzo, r.totale Totale
              FROM righe_intervento r JOIN interventi i ON i.id=r.intervento_id
              WHERE r.validazione='Validato J&J' AND COALESCE(r.stato_record,'Attivo')='Attivo' AND COALESCE(i.stato_record,'Attivo')='Attivo'
              ORDER BY i.data_intervento DESC""")
    st.dataframe(df, use_container_width=True)
    if not df.empty:
        st.download_button("Scarica Work Implant Excel", excel_bytes({"Work Implant": df}), "work_implant.xlsx")

elif menu in ["Customer Connect", "🔁 Customer Connect"]:
    admin_only()
    st.title("Customer Connect")
    st.write("Esclude automaticamente materiale Loan / Conto Visione.")
    df = q("""SELECT r.codice Codice, SUM(r.quantita) Quantita
              FROM righe_intervento r
              WHERE r.validazione='Validato J&J' AND r.reintegro=1 AND COALESCE(r.stato_record,'Attivo')='Attivo'
              GROUP BY r.codice ORDER BY r.codice""")
    st.dataframe(df, use_container_width=True)
    if not df.empty:
        st.download_button("Scarica Excel Customer Connect", excel_bytes({"Customer Connect": df}), "customer_connect.xlsx")

elif False and menu == "Ordini e chiusure":
    admin_only()
    st.title("Ordini e chiusure")
    tab1, tab2, tab3 = st.tabs(["Order History", "Order Detail", "Chiusure J&J"])
    with tab1:
        f = st.file_uploader("Order History Excel", type=["xlsx","xls"])
        if f:
            df = norm(pd.read_excel(f)); st.dataframe(df.head(20), use_container_width=True)
            cols = list(df.columns)
            no = st.selectbox("Numero ordine", cols)
            tot = st.selectbox("Totale", cols)
            po = st.selectbox("Riferimento PO", [""]+cols)
            data = st.selectbox("Data ordine", [""]+cols)
            cliente = st.selectbox("Cliente", [""]+cols)
            stato = st.selectbox("Stato", [""]+cols)
            if st.button("Importa Order History"):
                c=get_conn()
                for _,r in df.iterrows():
                    c.execute("INSERT INTO order_history(numero_ordine,riferimento_po,data_ordine,cliente,stato,totale) VALUES(?,?,?,?,?,?)", (str(r[no]), "" if not po else str(r[po]), "" if not data else str(r[data]), "" if not cliente else str(r[cliente]), "" if not stato else str(r[stato]), money(r[tot])))
                c.commit(); c.close(); st.success("Importato")
    with tab2:
        f = st.file_uploader("Order Detail Excel", type=["xlsx","xls"])
        if f:
            df = norm(pd.read_excel(f)); st.dataframe(df.head(20), use_container_width=True)
            cols=list(df.columns)
            numero = st.text_input("Numero ordine J&J")
            cod = st.selectbox("Codice", cols)
            qty = st.selectbox("Quantità", cols)
            pre = st.selectbox("Prezzo", [""]+cols)
            tot = st.selectbox("Totale", [""]+cols)
            des = st.selectbox("Descrizione", [""]+cols)
            if st.button("Importa Order Detail"):
                c=get_conn()
                for _,r in df.iterrows():
                    c.execute("INSERT INTO order_details(numero_ordine,codice,descrizione,quantita,prezzo,totale) VALUES(?,?,?,?,?,?)", (numero,str(r[cod]),"" if not des else str(r[des]),money(r[qty]) or 0, money(r[pre]) if pre else None, money(r[tot]) if tot else None))
                c.commit(); c.close(); st.success("Importato")
    with tab3:
        f = st.file_uploader("Chiusura J&J Excel", type=["xlsx","xls"])
        if f:
            df = norm(pd.read_excel(f)); st.dataframe(df.head(20), use_container_width=True)
            cols=list(df.columns)
            mese = st.text_input("Mese")
            ordine = st.selectbox("Numero ordine", [""]+cols)
            cod = st.selectbox("Codice", [""]+cols)
            val = st.selectbox("Valore", cols)
            qty = st.selectbox("Quantità", [""]+cols)
            des = st.selectbox("Descrizione", [""]+cols)
            if st.button("Importa chiusura"):
                c=get_conn()
                for _,r in df.iterrows():
                    c.execute("INSERT INTO chiusure(mese,numero_ordine,codice,descrizione,quantita,valore) VALUES(?,?,?,?,?,?)", (mese, "" if not ordine else str(r[ordine]), "" if not cod else str(r[cod]), "" if not des else str(r[des]), money(r[qty]) if qty else None, money(r[val])))
                c.commit(); c.close(); st.success("Importato")

elif False and menu == "Riconciliazione":
    admin_only()
    st.title("Riconciliazione")
    wi = q("""SELECT i.id intervento, i.data_intervento, i.cliente, i.cartella_clinica, i.agente, COALESCE(SUM(r.totale),0) valore_teorico
              FROM interventi i LEFT JOIN righe_intervento r ON r.intervento_id=i.id
              GROUP BY i.id ORDER BY i.data_intervento DESC""")
    oc = q("""SELECT numero_ordine, SUM(valore) valore_chiuso FROM chiusure GROUP BY numero_ordine""")
    oh = q("SELECT numero_ordine, data_ordine, cliente, totale FROM order_history")
    st.subheader("Interventi")
    st.dataframe(wi, use_container_width=True)
    st.subheader("Ordini vs chiusure")
    if not oh.empty:
        m = oh.merge(oc, on="numero_ordine", how="left")
        m["differenza"] = m["totale"].fillna(0) - m["valore_chiuso"].fillna(0)
        st.dataframe(m, use_container_width=True)
        st.download_button("Scarica riconciliazione Excel", excel_bytes({"Interventi":wi, "Ordini_vs_chiusure":m}), "riconciliazione.xlsx")

elif menu in ["Anomalie", "⚠️ Anomalie"]:
    st.title("Anomalie")
    st.dataframe(q("SELECT * FROM anomalie ORDER BY id DESC"), use_container_width=True)


elif False and menu == "Gestione dati":
    admin_only()
    st.title("🛠️ Gestione dati")
    st.markdown('<div class="ok-box">Da qui puoi modificare o eliminare/annullare tutto quello che viene inserito. Ogni modifica viene registrata in Audit Log.</div>', unsafe_allow_html=True)
    tab = st.selectbox("Scegli cosa gestire", [
        "clienti", "magazzino", "offerte_header", "offerte_clienti", "offerte_prezzi",
        "interventi", "righe_intervento", "ddt", "ddt_righe",
        "order_history", "order_details", "chiusure", "anomalie"
    ])
    editable_manager(tab, f"Gestione {tab}")
    st.subheader("Audit Log")
    try:
        st.dataframe(q("SELECT * FROM audit_log ORDER BY id DESC"), use_container_width=True)
    except Exception:
        st.info("Audit log non ancora disponibile.")



elif menu in ["👥 Clienti", "Clienti"]:
    admin_only()
    st.title("👥 Clienti")
    st.write("Importa, visualizza, modifica o annulla i clienti.")

    tab1, tab2 = st.tabs(["Importa anagrafica", "Gestisci clienti"])

    with tab1:
        f = st.file_uploader("Anagrafica clienti Excel", type=["xlsx","xls"], key="clienti_fix32")
        if f:
            df = norm(pd.read_excel(f))
            st.write(f"Righe lette dal file: **{len(df)}**")
            st.dataframe(df, use_container_width=True)

            cols = list(df.columns)
            cc = st.selectbox("Colonna Codice cliente", cols, key="cc32")
            desc = st.selectbox("Colonna Descrizione", cols, index=cols.index("Descrizione") if "Descrizione" in cols else 0, key="desc32")
            city = st.selectbox("Colonna Città", [""] + cols, key="city32")
            prov = st.selectbox("Colonna Provincia", [""] + cols, key="prov32")
            piva = st.selectbox("Colonna P.IVA", [""] + cols, key="piva32")

            if st.button("Importa / aggiorna clienti", use_container_width=True, key="import_clienti32"):
                c = get_conn()
                imported = 0
                skipped = 0
                for _, r in df.iterrows():
                    codice = str(r[cc]).strip()
                    if not codice or codice.lower() == "nan":
                        skipped += 1
                        continue
                    c.execute("""INSERT OR REPLACE INTO clienti(codice_cliente,descrizione,citta,provincia,piva,stato_record)
                                 VALUES(?,?,?,?,?,'Attivo')""",
                              (
                                  codice,
                                  str(r[desc]),
                                  "" if not city else str(r[city]),
                                  "" if not prov else str(r[prov]),
                                  "" if not piva else str(r[piva]),
                              ))
                    imported += 1
                c.commit()
                c.close()
                st.success(f"Clienti importati/aggiornati: {imported}. Righe scartate: {skipped}.")

    with tab2:
        dfc = q("""SELECT id,codice_cliente,descrizione,citta,provincia,piva,
                          COALESCE(stato_record,'Attivo') stato_record
                   FROM clienti
                   ORDER BY descrizione""")
        st.write(f"Clienti presenti: **{len(dfc)}**")
        st.dataframe(dfc, use_container_width=True)
        if len(dfc) > 0:
            editable_manager("clienti", "Modifica / annulla clienti")

elif menu in ["🏷️ Alias strutture", "Alias strutture"]:
    admin_only()
    st.title("🏷️ Alias strutture")
    st.write("Collega i nomi letti da OCR ai codici cliente interni.")

    clienti_df = q("SELECT codice_cliente, descrizione FROM clienti ORDER BY descrizione")
    if clienti_df.empty:
        st.warning("Importa prima l'anagrafica clienti.")
    else:
        with st.form("alias_form_fix32"):
            alias = st.text_input("Alias struttura", placeholder="es. Federico II / A.O.U. Federico II / Cardarelli")
            cliente_label = st.selectbox("Cliente corretto", [f"{r.codice_cliente} - {r.descrizione}" for r in clienti_df.itertuples()])
            priorita = st.number_input("Priorità", min_value=1, max_value=999, value=100)
            note = st.text_input("Note")
            ok = st.form_submit_button("Salva alias", use_container_width=True)
        if ok and alias:
            codice = cliente_label.split(" - ")[0]
            descr = " - ".join(cliente_label.split(" - ")[1:])
            c = get_conn()
            c.execute("""INSERT OR REPLACE INTO alias_strutture(alias,codice_cliente,descrizione_cliente,priorita,note)
                         VALUES(?,?,?,?,?)""", (alias, codice, descr, priorita, note))
            c.commit()
            c.close()
            st.success("Alias salvato.")

    dfa = q("SELECT * FROM alias_strutture ORDER BY priorita, alias")
    st.write(f"Alias presenti: **{len(dfa)}**")
    st.dataframe(dfa, use_container_width=True)

    test = st.text_input("Test riconoscimento struttura", placeholder="Scrivi ad esempio Federico II")
    if test:
        c = get_conn()
        res = resolve_cliente_from_structure(c, test)
        c.close()
        if res:
            st.success(f"Riconosciuto: {res['codice_cliente']} - {res['descrizione']} | metodo {res['metodo']} | score {res['score']}")
        else:
            st.error("Nessun cliente trovato. Aggiungi un alias.")

elif menu in ["📦 Magazzino", "Magazzino"]:
    admin_only()
    st.title("📦 Magazzino")

    tab1, tab2 = st.tabs(["Importa giacenze", "Gestisci magazzino"])

    with tab1:
        f = st.file_uploader("Giacenze magazzino Excel", type=["xlsx","xls"], key="mag_fix32")
        if f:
            df = norm(pd.read_excel(f))
            st.write(f"Righe lette dal file: **{len(df)}**")
            st.dataframe(df, use_container_width=True)

            cols = list(df.columns)
            cod = st.selectbox("Colonna Codice", cols, key="codmag32")
            lot = st.selectbox("Colonna Lotto", cols, key="lotmag32")
            qty = st.selectbox("Colonna Quantità", cols, key="qtymag32")
            des = st.selectbox("Colonna Descrizione", [""] + cols, key="desmag32")
            sca = st.selectbox("Colonna Scadenza", [""] + cols, key="scamag32")
            ori = st.selectbox("Origine", ["CONTO DEPOSITO", "LOAN / CONTO VISIONE"], key="orimag32")

            if st.button("Importa magazzino", use_container_width=True, key="importmag32"):
                c = get_conn()
                imported = 0
                skipped = 0
                for _, r in df.iterrows():
                    codice = str(r[cod]).strip()
                    lotto = str(r[lot]).strip()
                    if not codice or codice.lower() == "nan" or not lotto or lotto.lower() == "nan":
                        skipped += 1
                        continue
                    qta = pd.to_numeric(r[qty], errors="coerce")
                    qta = 0 if pd.isna(qta) else float(qta)
                    c.execute("""INSERT OR REPLACE INTO magazzino(codice,descrizione,lotto,scadenza,quantita,origine,stato_record)
                                 VALUES(?,?,?,?,?,?,'Attivo')""",
                              (
                                  codice,
                                  "" if not des else str(r[des]),
                                  lotto,
                                  "" if not sca else str(r[sca]),
                                  qta,
                                  ori,
                              ))
                    imported += 1
                c.commit()
                c.close()
                st.success(f"Righe magazzino importate/aggiornate: {imported}. Scartate: {skipped}.")

    with tab2:
        dfm = q("""SELECT id,codice,descrizione,lotto,scadenza,quantita,ubicazione,origine,
                          COALESCE(stato_record,'Attivo') stato_record
                   FROM magazzino
                   ORDER BY id DESC""")
        st.write(f"Righe magazzino presenti: **{len(dfm)}**")
        st.dataframe(dfm, use_container_width=True)
        if len(dfm) > 0:
            editable_manager("magazzino", "Modifica / annulla magazzino")

elif False and menu == "Export completo":
    st.title("Export completo")
    tables = ["clienti","agenti","magazzino","offerte_header","offerte_clienti","offerte_prezzi","interventi","righe_intervento","ddt","ddt_righe","order_history","order_details","chiusure","anomalie"]
    sheets = {t: q(f"SELECT * FROM {t}") for t in tables}
    st.download_button("Scarica backup completo", excel_bytes(sheets), "orthoflow_backup_completo.xlsx")


elif menu in ["👥 Clienti", "Clienti"]:
    admin_only()
    st.title("👥 Clienti")
    st.write("Importa, visualizza, modifica o annulla i clienti.")

    tab1, tab2 = st.tabs(["Importa anagrafica", "Gestisci clienti"])

    with tab1:
        f = st.file_uploader("Anagrafica clienti Excel", type=["xlsx","xls"], key="clienti_fix33")
        if f:
            df = norm(pd.read_excel(f))
            st.write(f"Righe lette dal file: **{len(df)}**")
            st.dataframe(df, use_container_width=True)

            cols = list(df.columns)
            cc = st.selectbox("Colonna Codice cliente", cols, key="cc33")
            desc = st.selectbox("Colonna Descrizione", cols, index=cols.index("Descrizione") if "Descrizione" in cols else 0, key="desc33")
            city = st.selectbox("Colonna Città", [""] + cols, key="city33")
            prov = st.selectbox("Colonna Provincia", [""] + cols, key="prov33")
            piva = st.selectbox("Colonna P.IVA", [""] + cols, key="piva33")

            if st.button("Importa / aggiorna clienti", use_container_width=True, key="import_clienti33"):
                c = get_conn()
                imported = 0
                skipped = 0
                for _, r in df.iterrows():
                    codice = str(r[cc]).strip()
                    if not codice or codice.lower() == "nan":
                        skipped += 1
                        continue
                    c.execute("""INSERT OR REPLACE INTO clienti(codice_cliente,descrizione,citta,provincia,piva,stato_record)
                                 VALUES(?,?,?,?,?,'Attivo')""",
                              (codice, str(r[desc]), "" if not city else str(r[city]), "" if not prov else str(r[prov]), "" if not piva else str(r[piva])))
                    imported += 1
                c.commit()
                c.close()
                st.success(f"Clienti importati/aggiornati: {imported}. Righe scartate: {skipped}.")

    with tab2:
        dfc = q("""SELECT id,codice_cliente,descrizione,citta,provincia,piva,
                          COALESCE(stato_record,'Attivo') stato_record
                   FROM clienti
                   ORDER BY descrizione""")
        st.write(f"Clienti presenti: **{len(dfc)}**")
        st.dataframe(dfc, use_container_width=True)
        if len(dfc) > 0:
            editable_manager("clienti", "Modifica / annulla clienti")

elif menu in ["🏷️ Alias strutture", "Alias strutture"]:
    admin_only()
    st.title("🏷️ Alias strutture")
    st.write("Collega i nomi letti da OCR ai codici cliente interni.")

    clienti_df = q("SELECT codice_cliente, descrizione FROM clienti ORDER BY descrizione")
    if clienti_df.empty:
        st.warning("Importa prima l'anagrafica clienti.")
    else:
        with st.form("alias_form_fix33"):
            alias = st.text_input("Alias struttura", placeholder="es. Federico II / A.O.U. Federico II / Cardarelli")
            cliente_label = st.selectbox("Cliente corretto", [f"{r.codice_cliente} - {r.descrizione}" for r in clienti_df.itertuples()])
            priorita = st.number_input("Priorità", min_value=1, max_value=999, value=100)
            note = st.text_input("Note")
            ok = st.form_submit_button("Salva alias", use_container_width=True)
        if ok and alias:
            codice = cliente_label.split(" - ")[0]
            descr = " - ".join(cliente_label.split(" - ")[1:])
            c = get_conn()
            c.execute("""INSERT OR REPLACE INTO alias_strutture(alias,codice_cliente,descrizione_cliente,priorita,note)
                         VALUES(?,?,?,?,?)""", (alias, codice, descr, priorita, note))
            c.commit()
            c.close()
            st.success("Alias salvato.")

    dfa = q("SELECT * FROM alias_strutture ORDER BY priorita, alias")
    st.write(f"Alias presenti: **{len(dfa)}**")
    st.dataframe(dfa, use_container_width=True)

    test = st.text_input("Test riconoscimento struttura", placeholder="Scrivi ad esempio Federico II")
    if test:
        c = get_conn()
        res = resolve_cliente_from_structure(c, test)
        c.close()
        if res:
            st.success(f"Riconosciuto: {res['codice_cliente']} - {res['descrizione']} | metodo {res['metodo']} | score {res['score']}")
        else:
            st.error("Nessun cliente trovato. Aggiungi un alias.")

elif menu in ["📦 Magazzino", "Magazzino"]:
    admin_only()
    st.title("📦 Magazzino")

    tab1, tab2 = st.tabs(["Importa giacenze", "Gestisci magazzino"])

    with tab1:
        f = st.file_uploader("Giacenze magazzino Excel", type=["xlsx","xls"], key="mag_fix33")
        if f:
            df = norm(pd.read_excel(f))
            st.write(f"Righe lette dal file: **{len(df)}**")
            st.dataframe(df, use_container_width=True)

            cols = list(df.columns)
            cod = st.selectbox("Colonna Codice", cols, key="codmag33")
            lot = st.selectbox("Colonna Lotto", cols, key="lotmag33")
            qty = st.selectbox("Colonna Quantità", cols, key="qtymag33")
            des = st.selectbox("Colonna Descrizione", [""] + cols, key="desmag33")
            sca = st.selectbox("Colonna Scadenza", [""] + cols, key="scamag33")
            ori = st.selectbox("Origine", ["CONTO DEPOSITO", "LOAN / CONTO VISIONE"], key="orimag33")

            if st.button("Importa magazzino", use_container_width=True, key="importmag33"):
                c = get_conn()
                imported = 0
                skipped = 0
                for _, r in df.iterrows():
                    codice = str(r[cod]).strip()
                    lotto = str(r[lot]).strip()
                    if not codice or codice.lower() == "nan" or not lotto or lotto.lower() == "nan":
                        skipped += 1
                        continue
                    qta = pd.to_numeric(r[qty], errors="coerce")
                    qta = 0 if pd.isna(qta) else float(qta)
                    c.execute("""INSERT OR REPLACE INTO magazzino(codice,descrizione,lotto,scadenza,quantita,origine,stato_record)
                                 VALUES(?,?,?,?,?,?,'Attivo')""",
                              (codice, "" if not des else str(r[des]), lotto, "" if not sca else str(r[sca]), qta, ori))
                    imported += 1
                c.commit()
                c.close()
                st.success(f"Righe magazzino importate/aggiornate: {imported}. Scartate: {skipped}.")

    with tab2:
        dfm = q("""SELECT id,codice,descrizione,lotto,scadenza,quantita,ubicazione,origine,
                          COALESCE(stato_record,'Attivo') stato_record
                   FROM magazzino
                   ORDER BY id DESC""")
        st.write(f"Righe magazzino presenti: **{len(dfm)}**")
        st.dataframe(dfm, use_container_width=True)
        if len(dfm) > 0:
            editable_manager("magazzino", "Modifica / annulla magazzino")

elif menu in ["📊 Fatturato e KPI", "Fatturato e KPI", "KPI Agenti"]:
    admin_only()
    st.title("📊 Fatturato e KPI")
    st.write("Area riservata Admin.")

    c = get_conn()
    fatturato = c.execute("""SELECT COALESCE(SUM(totale),0) n
                             FROM righe_intervento
                             WHERE COALESCE(stato_record,'Attivo')='Attivo'
                             AND validazione='Validato J&J'""").fetchone()["n"]
    interventi = c.execute("""SELECT COUNT(*) n
                              FROM interventi
                              WHERE COALESCE(stato_record,'Attivo')='Attivo'""").fetchone()["n"]
    righe = c.execute("""SELECT COUNT(*) n
                         FROM righe_intervento
                         WHERE COALESCE(stato_record,'Attivo')='Attivo'""").fetchone()["n"]
    anomalie = c.execute("""SELECT COUNT(*) n
                            FROM anomalie
                            WHERE stato='Aperta'""").fetchone()["n"]
    c.close()

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Fatturato teorico", f"€ {fatturato:,.2f}")
    m2.metric("Interventi", interventi)
    m3.metric("Righe impiantate", righe)
    m4.metric("Anomalie aperte", anomalie)

    st.subheader("Fatturato per agente")
    df_agenti = q("""SELECT i.agente,
                            COUNT(DISTINCT i.id) interventi,
                            COUNT(r.id) righe,
                            COALESCE(SUM(r.totale),0) fatturato
                     FROM interventi i
                     LEFT JOIN righe_intervento r
                       ON r.intervento_id=i.id
                       AND COALESCE(r.stato_record,'Attivo')='Attivo'
                     WHERE COALESCE(i.stato_record,'Attivo')='Attivo'
                     GROUP BY i.agente
                     ORDER BY fatturato DESC""")
    st.dataframe(df_agenti, use_container_width=True)

    st.subheader("Fatturato per struttura")
    df_clienti = q("""SELECT i.cliente,
                            COUNT(DISTINCT i.id) interventi,
                            COALESCE(SUM(r.totale),0) fatturato
                     FROM interventi i
                     LEFT JOIN righe_intervento r
                       ON r.intervento_id=i.id
                       AND COALESCE(r.stato_record,'Attivo')='Attivo'
                     WHERE COALESCE(i.stato_record,'Attivo')='Attivo'
                     GROUP BY i.cliente
                     ORDER BY fatturato DESC""")
    st.dataframe(df_clienti, use_container_width=True)

elif menu in ["🛠️ Gestione dati", "Gestione dati"]:
    admin_only()
    st.title("🛠️ Gestione dati")
    st.write("Modifica o annulla i dati inseriti. Area riservata Admin.")

    tables = [
        "clienti",
        "alias_strutture",
        "magazzino",
        "offerte_header",
        "offerte_clienti",
        "offerte_prezzi",
        "interventi",
        "righe_intervento",
        "ddt",
        "ddt_righe",
        "order_history",
        "order_details",
        "chiusure",
        "anomalie",
    ]
    table = st.selectbox("Tabella da gestire", tables, key="gestione_table33")
    editable_manager(table, f"Gestione {table}")

    st.subheader("Audit Log")
    try:
        st.dataframe(q("SELECT * FROM audit_log ORDER BY id DESC"), use_container_width=True)
    except Exception:
        st.info("Audit Log non ancora disponibile.")

elif menu in ["🔍 Riconciliazione", "Riconciliazione"]:
    admin_only()
    st.title("🔍 Riconciliazione")
    st.write("Controllo tra interventi, righe impiantate e valorizzazione teorica.")

    df = q("""SELECT i.id intervento,
                     i.data_intervento,
                     i.codice_cliente,
                     i.cliente,
                     i.cartella_clinica,
                     i.agente,
                     i.linea,
                     COUNT(r.id) righe,
                     COALESCE(SUM(r.totale),0) valore_teorico
              FROM interventi i
              LEFT JOIN righe_intervento r
                ON r.intervento_id=i.id
                AND COALESCE(r.stato_record,'Attivo')='Attivo'
              WHERE COALESCE(i.stato_record,'Attivo')='Attivo'
              GROUP BY i.id
              ORDER BY i.id DESC""")
    st.dataframe(df, use_container_width=True)

elif menu in ["🧾 Ordini e chiusure", "Ordini e chiusure"]:
    admin_only()
    st.title("🧾 Ordini e chiusure")
    st.write("Gestione dati ordini e chiusure.")
    tab1, tab2, tab3 = st.tabs(["Order History", "Order Details", "Chiusure"])
    with tab1:
        editable_manager("order_history", "Order History")
    with tab2:
        editable_manager("order_details", "Order Details")
    with tab3:
        editable_manager("chiusure", "Chiusure")

elif menu in ["📤 Export completo", "Export completo"]:
    admin_only()
    st.title("📤 Export completo")

    tables = [
        "clienti",
        "alias_strutture",
        "agenti",
        "magazzino",
        "offerte_header",
        "offerte_clienti",
        "offerte_prezzi",
        "interventi",
        "righe_intervento",
        "ddt",
        "ddt_righe",
        "order_history",
        "order_details",
        "chiusure",
        "anomalie",
        "audit_log",
    ]
    sheets = {}
    for t in tables:
        try:
            sheets[t] = q(f"SELECT * FROM {t}")
        except Exception:
            pass

    st.download_button(
        "Scarica backup completo Excel",
        excel_bytes(sheets),
        "orthoflow_backup_completo.xlsx",
        use_container_width=True,
    )
