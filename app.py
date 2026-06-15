
import streamlit as st
import pandas as pd
from datetime import date
from database import init_db, get_conn
from helpers import *
from supabase_persistence import upload_db_if_available
from ai_ocr import ai_enabled, analyze_image, normalize_ai_items
import json

st.set_page_config(page_title="OrthoFlow Control Tower v1.0", layout="wide")
init_db()

def q(sql, params=()):
    c = get_conn()
    df = pd.read_sql_query(sql, c, params=params)
    c.close()
    return df

def cloud_backup_now():
    try:
        upload_db_if_available()
    except Exception:
        pass



def _idx(cols, wanted, default=0):
    """Restituisce indice della colonna se presente."""
    for w in wanted:
        if w in cols:
            return cols.index(w)
    for i, c in enumerate(cols):
        lc = str(c).lower()
        if any(str(w).lower() in lc for w in wanted):
            return i
    return default

def _idx_optional(cols, wanted):
    opts = [""] + cols
    for w in wanted:
        if w in cols:
            return opts.index(w)
    for c in cols:
        lc = str(c).lower()
        if any(str(w).lower() in lc for w in wanted):
            return opts.index(c)
    return 0

def _clean_import_code(v):
    """Mantiene il codice come testo, evitando .0 finale da Excel."""
    if pd.isna(v):
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()



def admin_only():
    if st.session_state.get("ruolo") != "Admin":
        st.error("Area riservata Admin.")
        st.stop()

def table_exists(table: str) -> bool:
    c = get_conn()
    try:
        r = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        return r is not None
    finally:
        c.close()

def editable_table(table: str, title: str):
    st.subheader(title)
    if not table_exists(table):
        st.warning(f"Tabella {table} non presente.")
        return
    df = q(f"SELECT * FROM {table} ORDER BY id DESC" if table != "agenti" else f"SELECT * FROM {table} ORDER BY nome")
    st.write(f"Righe presenti: **{len(df)}**")
    if df.empty:
        st.info("Nessun dato presente.")
        return
    edited = st.data_editor(df, use_container_width=True, num_rows="dynamic", key=f"edit_{table}")
    c1, c2 = st.columns(2)
    with c1:
        if st.button(f"Salva modifiche {table}", key=f"save_{table}", use_container_width=True):
            c = get_conn()
            try:
                original_ids = set(df["id"].dropna().astype(int).tolist()) if "id" in df.columns else set()
                edited_ids = set(edited["id"].dropna().astype(int).tolist()) if "id" in edited.columns else set()
                # cancella righe rimosse dall'editor
                for rid in original_ids - edited_ids:
                    c.execute(f"DELETE FROM {table} WHERE id=?", (int(rid),))
                cols = [col for col in edited.columns if col != "id"]
                for _, row in edited.iterrows():
                    vals = [None if pd.isna(row.get(col)) else row.get(col) for col in cols]
                    rid = row.get("id") if "id" in edited.columns else None
                    if pd.notna(rid) and str(rid).strip() != "":
                        set_clause = ", ".join([f"{col}=?" for col in cols])
                        c.execute(f"UPDATE {table} SET {set_clause} WHERE id=?", vals + [int(rid)])
                    else:
                        col_clause = ", ".join(cols)
                        ph = ", ".join(["?"] * len(cols))
                        c.execute(f"INSERT INTO {table} ({col_clause}) VALUES ({ph})", vals)
                c.commit()
                st.success("Modifiche salvate.")
                st.rerun()
            finally:
                c.close()
    with c2:
        st.download_button(f"Scarica {table} Excel", excel_bytes({table: df}), f"{table}.xlsx", use_container_width=True)


def login():
    st.sidebar.title("OrthoFlow")
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
        st.title("OrthoFlow Control Tower v1.0")
        st.info("Accesso demo: admin / admin")
        return False
    st.sidebar.success(st.session_state.user)
    if st.sidebar.button("Esci"):
        st.session_state.clear()
        st.rerun()
    return True

if not login():
    st.stop()

admin_menu = [
    "Dashboard",
    "Clienti",
    "Alias strutture",
    "Magazzino",
    "KPI Agenti",
    "Loan Monitor",
    "Scadenze",
    "Import iniziali",
    "Offerte",
    "DDT carico / Loan",
    "Scarico sala",
    "Work Implant",
    "Customer Connect",
    "Ordini e chiusure",
    "Riconciliazione",
    "Anomalie",
    "Gestione dati",
    "Export completo"
]
collab_menu = [
    "Dashboard",
    "Scarico sala"
]

menu_list = admin_menu if st.session_state.get("ruolo") == "Admin" else collab_menu
default_index = 0
if st.session_state.get("_go_to") in menu_list:
    default_index = menu_list.index(st.session_state.pop("_go_to"))

menu = st.sidebar.radio("Menu", menu_list, index=default_index)

if menu == "Dashboard":
    st.title("🏥 OrthoFlow Control Tower")
    st.caption("Gestione scarichi sala, DDT, offerte, magazzino e fatturato teorico. Modalità J&J Safe Match: la S sterile resta discriminante. Backup Supabase persistente attivo se configurato.")

    is_admin_user = st.session_state.get("ruolo") == "Admin"

    c = get_conn()
    clienti_n = c.execute("SELECT COUNT(*) n FROM clienti").fetchone()["n"]
    mag_n = c.execute("SELECT COUNT(*) n FROM magazzino").fetchone()["n"]
    interventi_n = c.execute("SELECT COUNT(*) n FROM interventi").fetchone()["n"]
    anomalie_n = c.execute("SELECT COUNT(*) n FROM anomalie WHERE stato='Aperta'").fetchone()["n"]
    fatt_n = c.execute("SELECT COALESCE(SUM(totale),0) n FROM righe_intervento WHERE validazione='Validato J&J'").fetchone()["n"]
    c.close()

    if is_admin_user:
        cols = st.columns(5)
        cols[0].metric("Clienti", clienti_n)
        cols[1].metric("Righe magazzino", mag_n)
        cols[2].metric("Interventi", interventi_n)
        cols[3].metric("Anomalie aperte", anomalie_n)
        cols[4].metric("Fatturato teorico", f"€ {fatt_n:,.2f}")
    else:
        st.info("Accesso collaboratore: puoi inserire solo nuovi scarichi sala.")

    st.subheader("Azioni rapide")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("📸 Nuovo scarico sala", use_container_width=True):
            st.session_state["_go_to"] = "Scarico sala"
            st.rerun()
    with c2:
        if is_admin_user:
            if st.button("🚚 Nuovo DDT / Loan", use_container_width=True):
                st.session_state["_go_to"] = "DDT carico / Loan"
                st.rerun()
        else:
            st.button("🚚 Nuovo DDT / Loan", disabled=True, use_container_width=True)

    if is_admin_user:
        st.subheader("Fatturato per agente")
        st.dataframe(q("""SELECT i.agente, COUNT(DISTINCT i.id) interventi, COALESCE(SUM(r.totale),0) fatturato
                          FROM interventi i LEFT JOIN righe_intervento r ON r.intervento_id=i.id
                          GROUP BY i.agente ORDER BY fatturato DESC"""), use_container_width=True)

    st.subheader("Istruzioni rapide")
    st.success("1. Carica foto/PDF dello scarico. 2. Controlla le righe estratte. 3. Conferma e salva.")


elif menu == "Clienti":
    admin_only()
    st.title("👥 Clienti")
    st.write("Importa, visualizza e modifica l'anagrafica clienti.")
    tab1, tab2 = st.tabs(["Importa clienti", "Gestisci clienti"])
    with tab1:
        f = st.file_uploader("Anagrafica clienti Excel", type=["xlsx", "xls"], key="clienti_page_upload")
        if f:
            df = norm(pd.read_excel(f))
            st.write(f"Righe lette: **{len(df)}**")
            st.dataframe(df.head(50), use_container_width=True)
            cols = list(df.columns)
            cc = st.selectbox("Colonna Codice cliente", cols, index=_idx(cols, ["Codice", "codice_cliente", "Cliente"]), key="clienti_page_cod")
            desc = st.selectbox("Colonna Descrizione", cols, index=_idx(cols, ["Descrizione", "Ragione sociale", "Cliente"], 1 if len(cols)>1 else 0), key="clienti_page_desc")
            city = st.selectbox("Colonna Città", [""] + cols, index=_idx_optional(cols, ["Città", "Citta", "Comune"]), key="clienti_page_city")
            prov = st.selectbox("Colonna Provincia", [""] + cols, index=_idx_optional(cols, ["Prov", "Provincia"]), key="clienti_page_prov")
            piva = st.selectbox("Colonna P.IVA", [""] + cols, index=_idx_optional(cols, ["Partita Iva", "P.IVA", "PIVA", "Partita IVA"]), key="clienti_page_piva")
            if st.button("Importa / aggiorna clienti", use_container_width=True, key="clienti_page_import"):
                c = get_conn(); n = 0; skipped = 0
                for _, r in df.iterrows():
                    codice = _clean_import_code(r[cc])
                    if not codice or codice.lower() == "nan":
                        skipped += 1; continue
                    c.execute("""INSERT OR REPLACE INTO clienti(codice_cliente,descrizione,citta,provincia,piva,stato_record)
                                 VALUES(?,?,?,?,?,'Attivo')""",
                              (codice, str(r[desc]), "" if not city else str(r[city]), "" if not prov else str(r[prov]), "" if not piva else str(r[piva])))
                    n += 1
                c.commit(); cloud_backup_now(); c.close()
                st.success(f"Clienti importati/aggiornati: {n}. Scartati: {skipped}.")
    with tab2:
        editable_table("clienti", "Gestisci clienti")

elif menu == "Alias strutture":
    admin_only()
    st.title("🏷️ Alias strutture")
    st.write("Collega i nomi letti dall'OCR ai codici cliente interni.")
    clienti_df = q("SELECT codice_cliente, descrizione FROM clienti ORDER BY descrizione")
    if clienti_df.empty:
        st.warning("Importa prima l'anagrafica clienti.")
    else:
        with st.form("alias_form"):
            alias = st.text_input("Alias struttura", placeholder="es. Federico II / A.O.U. Federico II / Azienda Ospedaliera Universitaria Federico II")
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
            c.commit(); cloud_backup_now(); c.close(); st.success("Alias salvato.")
    editable_table("alias_strutture", "Alias presenti")
    test = st.text_input("Test riconoscimento struttura")
    if test:
        c = get_conn(); res = resolve_cliente_from_structure(c, test); c.close()
        if res:
            st.success(f"Riconosciuto: {res['codice_cliente']} - {res['descrizione']} | {res['metodo']} | score {res['score']}")
        else:
            st.error("Nessun cliente trovato. Aggiungi un alias.")

elif menu == "Magazzino":
    admin_only()
    st.title("📦 Magazzino")
    tab1, tab2 = st.tabs(["Importa giacenze", "Gestisci magazzino"])
    with tab1:
        f = st.file_uploader("Giacenze magazzino Excel", type=["xlsx", "xls"], key="magazzino_page_upload")
        if f:
            df = norm(pd.read_excel(f))
            st.write(f"Righe lette: **{len(df)}**")
            st.dataframe(df.head(50), use_container_width=True)
            cols = list(df.columns)
            cod = st.selectbox("Colonna Codice", cols, index=_idx(cols, ["Articolo", "Codice", "Codice prodotto"]), key="mag_page_cod")
            lot = st.selectbox("Colonna Lotto", cols, index=_idx(cols, ["Lotto", "LOT", "Batch"], 2 if len(cols)>2 else 0), key="mag_page_lot")
            qty = st.selectbox("Colonna Quantità", cols, index=_idx(cols, ["Quantità", "Quantita", "Qta", "Qty"], 3 if len(cols)>3 else 0), key="mag_page_qty")
            des = st.selectbox("Colonna Descrizione", [""] + cols, index=_idx_optional(cols, ["Descr. articolo", "Descrizione articolo", "Descrizione", "Descr."]), key="mag_page_des")
            sca = st.selectbox("Colonna Scadenza", [""] + cols, index=_idx_optional(cols, ["Scadenza", "Data scadenza", "EXP"]), key="mag_page_sca")
            ori = st.selectbox("Origine", ["CONTO DEPOSITO", "LOAN / CONTO VISIONE"], key="mag_page_ori")
            only_pos = st.checkbox("Solo quantità positive (>0) consigliato per TTKEYS", value=True, key="mag_page_only_positive")
            if st.button("Importa / aggiorna magazzino", use_container_width=True, key="mag_page_import"):
                c = get_conn(); n = 0; skipped = 0
                for _, r in df.iterrows():
                    codice, lotto = _clean_import_code(r[cod]), _clean_import_code(r[lot])
                    if not codice or codice.lower()=="nan" or not lotto or lotto.lower()=="nan":
                        skipped += 1; continue
                    qta = money(r[qty]) or 0
                    if only_pos and qta <= 0:
                        skipped += 1; continue
                    c.execute("""INSERT INTO magazzino(codice,descrizione,lotto,scadenza,quantita,origine,stato_record)
                                 VALUES(?,?,?,?,?,?,'Attivo')
                                 ON CONFLICT(codice,lotto,origine) DO UPDATE SET quantita=excluded.quantita, descrizione=excluded.descrizione, scadenza=excluded.scadenza""",
                              (codice, "" if not des else str(r[des]), lotto, "" if not sca else str(r[sca]), qta, ori))
                    n += 1
                c.commit(); cloud_backup_now(); c.close(); st.success(f"Righe importate/aggiornate: {n}. Scartate: {skipped}.")
    with tab2:
        editable_table("magazzino", "Gestisci magazzino")

elif menu == "KPI Agenti":
    
    if st.session_state.get("ruolo") != "Admin":
        st.error("Area riservata Admin.")
        st.stop()

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

elif menu == "Loan Monitor":
    
    if st.session_state.get("ruolo") != "Admin":
        st.error("Area riservata Admin.")
        st.stop()

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

elif menu == "Scadenze":
    
    if st.session_state.get("ruolo") != "Admin":
        st.error("Area riservata Admin.")
        st.stop()

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
    
    if st.session_state.get("ruolo") != "Admin":
        st.error("Area riservata Admin.")
        st.stop()

    st.title("Import iniziali")
    tab1, tab2, tab3 = st.tabs(["Clienti", "Magazzino", "Agenti"])
    with tab1:
        f = st.file_uploader("Anagrafica clienti Excel", type=["xlsx","xls"], key="clienti")
        if f:
            df = norm(pd.read_excel(f))
            st.dataframe(df.head(20), use_container_width=True)
            cols = list(df.columns)
            cc = st.selectbox("Codice cliente", cols)
            desc = st.selectbox("Descrizione", cols)
            city = st.selectbox("Città", [""]+cols)
            prov = st.selectbox("Provincia", [""]+cols)
            piva = st.selectbox("P.IVA", [""]+cols)
            if st.button("Importa clienti"):
                c = get_conn()
                for _, r in df.iterrows():
                    c.execute("""INSERT OR REPLACE INTO clienti(codice_cliente,descrizione,citta,provincia,piva)
                                 VALUES(?,?,?,?,?)""", (str(r[cc]), str(r[desc]), "" if not city else str(r[city]), "" if not prov else str(r[prov]), "" if not piva else str(r[piva])))
                c.commit(); cloud_backup_now(); c.close()
                st.success("Clienti importati")
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
                    codice, lotto = _clean_import_code(r[cod]), _clean_import_code(r[lot])
                    if not codice or codice=="nan" or not lotto or lotto=="nan":
                        continue
                    qta = pd.to_numeric(r[qty], errors="coerce")
                    qta = 0 if pd.isna(qta) else float(qta)
                    c.execute("""INSERT OR REPLACE INTO magazzino(codice,descrizione,lotto,scadenza,quantita,origine)
                                 VALUES(?,?,?,?,?,?)""", (codice, "" if not des else str(r[des]), lotto, "" if not sca else str(r[sca]), qta, ori))
                    n += 1
                c.commit(); cloud_backup_now(); c.close()
                st.success(f"Importate {n} righe")
    with tab3:
        st.dataframe(q("SELECT * FROM agenti ORDER BY nome"), use_container_width=True)
        nome = st.text_input("Nuovo agente")
        if st.button("Aggiungi agente") and nome:
            c = get_conn(); c.execute("INSERT OR IGNORE INTO agenti(nome) VALUES(?)", (nome,)); c.commit(); cloud_backup_now(); c.close()
            st.success("Agente aggiunto")

elif menu == "Offerte":
    
    if st.session_state.get("ruolo") != "Admin":
        st.error("Area riservata Admin.")
        st.stop()

    st.title("💰 Offerte")
    st.write("Visualizza, importa, modifica e controlla le offerte caricate. J&J Safe Match: 413.050S ≠ 413.050.")

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "Crea offerta",
        "Importa prezzi",
        "Visualizza offerta",
        "Modifica offerta",
        "Controllo matching"
    ])

    with tab1:
        with st.form("offerta_v5_create"):
            nome = st.text_input("Nome offerta / gara")
            linea = st.selectbox("Linea", ["TRAUMA", "PROTESICA", "CMF", "SPINE", "SPORTS", "ALTRO"], key="v5_linea_create")
            di = st.text_input("Data inizio validità", "")
            dfine = st.text_input("Data fine validità", "")
            note = st.text_area("Note")
            clienti = st.text_area("Codici clienti associati, separati da virgola o a capo")
            ok = st.form_submit_button("Crea offerta", use_container_width=True)
        if ok:
            c = get_conn()
            cur = c.execute("INSERT INTO offerte_header(nome_offerta,linea,data_inizio,data_fine,note) VALUES(?,?,?,?,?)", (nome,linea,di,dfine,note))
            off_id = cur.lastrowid
            for x in clienti.replace(",", "\n").splitlines():
                x = x.strip()
                if x:
                    c.execute("INSERT INTO offerte_clienti(offerta_id,codice_cliente) VALUES(?,?)", (off_id, x))
            c.commit(); cloud_backup_now(); c.close()
            st.success(f"Offerta creata ID {off_id}")

    with tab2:
        offerte = q("SELECT id, nome_offerta, linea FROM offerte_header ORDER BY id DESC")
        if offerte.empty:
            st.info("Crea prima un'offerta.")
        else:
            sel = st.selectbox("Offerta", [f"{r.id} - {r.nome_offerta} ({r.linea})" for r in offerte.itertuples()], key="v5_offerta_import")
            off_id = int(sel.split(" - ")[0])
            f = st.file_uploader("Excel prezzi offerta", type=["xlsx","xls"], key="v5_prezzi_upload")
            if f:
                sheet = st.text_input("Nome foglio da leggere, lascia vuoto per il primo", "", key="v5_sheet")
                df = norm(pd.read_excel(f, sheet_name=sheet if sheet else 0))
                st.write(f"Righe lette: **{len(df)}**")
                st.dataframe(df.head(50), use_container_width=True)
                cols = list(df.columns)

                cod = st.selectbox("Codice prodotto", cols, index=_idx(cols, ["Codice Prodotto", "Codice prodotto", "codice", "Articolo"]), key="v5_cod")
                pre = st.selectbox("Prezzo", cols, index=_idx(cols, ["Prezzo unitario offerto cifre e lettere", "Prezzo", "prezzo"], 2 if len(cols)>2 else 0), key="v5_pre")
                des = st.selectbox("Descrizione", [""]+cols, index=_idx_optional(cols, ["Descrizione prodotto", "Descrizione", "descrizione"]), key="v5_des")
                iva = st.selectbox("IVA", [""]+cols, key="v5_iva")
                cnd = st.selectbox("CND", [""]+cols, key="v5_cnd")
                rdm = st.selectbox("RDM", [""]+cols, key="v5_rdm")

                if st.button("Importa / aggiungi prezzi", use_container_width=True, key="v5_import_prezzi"):
                    c = get_conn()
                    n = 0
                    skipped = 0
                    for _, r in df.iterrows():
                        prezzo = money(r[pre])
                        codice = _clean_import_code(r[cod])
                        if not codice or codice.lower()=="nan" or prezzo is None:
                            skipped += 1
                            continue
                        c.execute("""INSERT INTO offerte_prezzi(offerta_id,codice,descrizione,prezzo,iva,cnd,rdm)
                                     VALUES(?,?,?,?,?,?,?)""",
                                  (off_id,codice,"" if not des else str(r[des]),prezzo,"" if not iva else str(r[iva]),"" if not cnd else str(r[cnd]),"" if not rdm else str(r[rdm])))
                        n += 1
                    c.commit(); cloud_backup_now(); c.close()
                    st.success(f"Prezzi importati: {n}. Righe scartate: {skipped}.")

    with tab3:
        offerte = q("SELECT id, nome_offerta, linea FROM offerte_header ORDER BY id DESC")
        if offerte.empty:
            st.info("Nessuna offerta presente.")
        else:
            sel = st.selectbox("Seleziona offerta da visualizzare", [f"{r.id} - {r.nome_offerta} ({r.linea})" for r in offerte.itertuples()], key="v5_offerta_view")
            off_id = int(sel.split(" - ")[0])

            h = q("SELECT * FROM offerte_header WHERE id=?", (off_id,))
            cl = q("""SELECT oc.id, oc.codice_cliente, c.descrizione
                      FROM offerte_clienti oc
                      LEFT JOIN clienti c ON c.codice_cliente=oc.codice_cliente
                      WHERE oc.offerta_id=? ORDER BY oc.codice_cliente""", (off_id,))
            pr = q("SELECT * FROM offerte_prezzi WHERE offerta_id=? ORDER BY codice", (off_id,))

            st.subheader("Testata offerta")
            st.dataframe(h, use_container_width=True)
            st.subheader("Clienti associati")
            st.dataframe(cl, use_container_width=True)
            st.subheader(f"Prezzi offerta: {len(pr)} righe")
            search = st.text_input("Cerca codice/descrizione", key="v5_search_prezzi")
            if search:
                s = search.lower()
                pr_show = pr[pr.apply(lambda row: s in " ".join(map(str,row.values)).lower(), axis=1)]
            else:
                pr_show = pr
            st.dataframe(pr_show, use_container_width=True)
            st.download_button("Scarica offerta completa Excel", excel_bytes({"Testata": h, "Clienti": cl, "Prezzi": pr}), f"offerta_{off_id}.xlsx", use_container_width=True)

    with tab4:
        offerte = q("SELECT id, nome_offerta, linea FROM offerte_header ORDER BY id DESC")
        if offerte.empty:
            st.info("Nessuna offerta da modificare.")
        else:
            sel = st.selectbox("Offerta da modificare", [f"{r.id} - {r.nome_offerta} ({r.linea})" for r in offerte.itertuples()], key="v5_offerta_edit")
            off_id = int(sel.split(" - ")[0])

            st.subheader("Modifica testata")
            h = q("SELECT * FROM offerte_header WHERE id=?", (off_id,))
            h_edit = st.data_editor(h, use_container_width=True, num_rows="fixed", key="v5_edit_header")
            if st.button("Salva testata", key="v5_save_header", use_container_width=True):
                r = h_edit.iloc[0]
                c = get_conn()
                c.execute("""UPDATE offerte_header
                             SET nome_offerta=?, linea=?, data_inizio=?, data_fine=?, note=?
                             WHERE id=?""",
                          (str(r.get("nome_offerta","")), str(r.get("linea","")), str(r.get("data_inizio","")), str(r.get("data_fine","")), str(r.get("note","")), off_id))
                c.commit(); cloud_backup_now(); c.close()
                st.success("Testata aggiornata.")

            st.subheader("Modifica clienti associati")
            cl = q("SELECT id, offerta_id, codice_cliente FROM offerte_clienti WHERE offerta_id=? ORDER BY codice_cliente", (off_id,))
            cl_edit = st.data_editor(cl, use_container_width=True, num_rows="dynamic", key="v5_edit_clienti")
            if st.button("Salva clienti associati", key="v5_save_clienti", use_container_width=True):
                c = get_conn()
                c.execute("DELETE FROM offerte_clienti WHERE offerta_id=?", (off_id,))
                for _, r in cl_edit.iterrows():
                    codice_cliente = str(r.get("codice_cliente","")).strip()
                    if codice_cliente and codice_cliente.lower() != "nan":
                        c.execute("INSERT INTO offerte_clienti(offerta_id,codice_cliente) VALUES(?,?)", (off_id, codice_cliente))
                c.commit(); cloud_backup_now(); c.close()
                st.success("Clienti offerta aggiornati.")

            st.subheader("Modifica prezzi")
            pr = q("SELECT id, offerta_id, codice, descrizione, prezzo, iva, cnd, rdm FROM offerte_prezzi WHERE offerta_id=? ORDER BY codice", (off_id,))
            filtro = st.text_input("Filtro prezzi da modificare", key="v5_filter_edit_prices")
            if filtro:
                f = filtro.lower()
                pr_view = pr[pr.apply(lambda row: f in " ".join(map(str,row.values)).lower(), axis=1)]
            else:
                pr_view = pr.head(300)
                st.caption("Mostro le prime 300 righe. Usa il filtro per modificare un codice specifico.")

            pr_edit = st.data_editor(pr_view, use_container_width=True, num_rows="dynamic", key="v5_edit_prices")
            if st.button("Salva modifiche prezzi visibili", key="v5_save_prices", use_container_width=True):
                c = get_conn()
                saved = 0
                inserted = 0
                for _, r in pr_edit.iterrows():
                    rid = r.get("id")
                    codice = str(r.get("codice","")).strip()
                    if not codice or codice.lower()=="nan":
                        continue
                    prezzo = money(r.get("prezzo"))
                    if pd.notna(rid) and str(rid).strip() and str(rid).lower() != "nan":
                        c.execute("""UPDATE offerte_prezzi
                                     SET codice=?, descrizione=?, prezzo=?, iva=?, cnd=?, rdm=?
                                     WHERE id=?""",
                                  (codice, str(r.get("descrizione","")), prezzo, str(r.get("iva","")), str(r.get("cnd","")), str(r.get("rdm","")), int(rid)))
                        saved += 1
                    else:
                        c.execute("""INSERT INTO offerte_prezzi(offerta_id,codice,descrizione,prezzo,iva,cnd,rdm)
                                     VALUES(?,?,?,?,?,?,?)""",
                                  (off_id, codice, str(r.get("descrizione","")), prezzo, str(r.get("iva","")), str(r.get("cnd","")), str(r.get("rdm",""))))
                        inserted += 1
                c.commit(); cloud_backup_now(); c.close()
                st.success(f"Prezzi aggiornati: {saved}. Nuove righe: {inserted}.")

            st.warning("Eliminazione completa offerta: usare solo se sei sicuro.")
            if st.button("Elimina completamente questa offerta", key="v5_delete_offer"):
                c = get_conn()
                c.execute("DELETE FROM offerte_prezzi WHERE offerta_id=?", (off_id,))
                c.execute("DELETE FROM offerte_clienti WHERE offerta_id=?", (off_id,))
                c.execute("DELETE FROM offerte_header WHERE id=?", (off_id,))
                c.commit(); cloud_backup_now(); c.close()
                st.success("Offerta eliminata. Ricarica la pagina.")

    with tab5:
        st.subheader("Test aggancio prezzo")
        clienti = q("SELECT codice_cliente || ' - ' || descrizione label FROM clienti ORDER BY descrizione")["label"].tolist()
        cliente_label = st.selectbox("Cliente", clienti if clienti else [""], key="v5_test_cliente")
        codice_cliente = cliente_label.split(" - ")[0] if cliente_label else ""
        codice_test = st.text_input("Codice prodotto da testare", placeholder="es. 413.050S oppure 413.050")
        linea_test = st.selectbox("Linea", ["TRAUMA", "PROTESICA", "CMF", "SPINE", "SPORTS", "ALTRO"], key="v5_test_linea")
        data_test = st.date_input("Data intervento", date.today(), key="v5_test_data")
        if st.button("Testa aggancio prezzo", use_container_width=True, key="v5_test_btn"):
            c = get_conn()
            prezzo = prezzo_per(c, codice_cliente, codice_test, linea_test, str(data_test))
            issues = diagnose_price(c, codice_cliente, codice_test, linea_test, str(data_test))
            c.close()
            if prezzo is not None:
                st.success(f"Prezzo trovato: € {prezzo:,.2f}")
            else:
                st.error("Prezzo non trovato.")
                for i in issues:
                    st.warning(i)

elif menu == "DDT carico / Loan":
    
    if st.session_state.get("ruolo") != "Admin":
        st.error("Area riservata Admin.")
        st.stop()

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
                    st.error("OCR AI non configurato. Controlla Streamlit Secrets: OPENAI_API_KEY e ENABLE_AI_OCR=true.")
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
        edited = st.data_editor(pd.DataFrame(rows), use_container_width=True, num_rows="dynamic", key="ddt_rows_editor_v5")
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
        c.commit(); cloud_backup_now(); c.close()
        st.success(f"DDT {ddt_id} creato. Righe caricate: {n}")
    st.subheader("DDT registrati")
    st.dataframe(q("SELECT * FROM ddt ORDER BY id DESC"), use_container_width=True)
elif menu == "Scarico sala":
    st.title("Scarico sala")
    st.info("J&J Safe Match: controlla sempre che il codice OCR mantenga la S finale se presente. 413.050S e 413.050 sono articoli diversi.")
    st.caption("Motore OCR AI: " + ("attivo" if ai_enabled() else "non configurato"))
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
                    st.error("OCR AI non configurato. Controlla Streamlit Secrets: OPENAI_API_KEY e ENABLE_AI_OCR=true.")
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
        st.subheader("2) Righe estratte da AI da verificare")
        df_ai = pd.DataFrame(st.session_state["ai_scarico_rows"])
        edited = st.data_editor(df_ai, use_container_width=True, num_rows="dynamic", key="scarico_ai_editor_v5")
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
        c.commit(); cloud_backup_now(); c.close()
        st.success(f"Intervento {iid} creato. Righe importate: {imported}")
elif menu == "Work Implant":
    
    if st.session_state.get("ruolo") != "Admin":
        st.error("Area riservata Admin.")
        st.stop()

    st.title("Work Implant")
    df = q("""SELECT i.data_intervento Data, i.cliente Clinica, i.cartella_clinica Cartella, i.agente Agente, i.linea Linea,
              r.codice Codice, r.descrizione Descrizione, r.lotto Lotto, r.quantita Quantita,
              r.origine Origine, r.prezzo Prezzo, r.totale Totale
              FROM righe_intervento r JOIN interventi i ON i.id=r.intervento_id
              WHERE r.validazione='Validato J&J'
              ORDER BY i.data_intervento DESC""")
    st.dataframe(df, use_container_width=True)
    if not df.empty:
        st.download_button("Scarica Work Implant Excel", excel_bytes({"Work Implant": df}), "work_implant.xlsx")

elif menu == "Customer Connect":
    
    if st.session_state.get("ruolo") != "Admin":
        st.error("Area riservata Admin.")
        st.stop()

    st.title("Customer Connect")
    st.write("Esclude automaticamente materiale Loan / Conto Visione.")
    df = q("""SELECT r.codice Codice, SUM(r.quantita) Quantita
              FROM righe_intervento r
              WHERE r.validazione='Validato J&J' AND r.reintegro=1
              GROUP BY r.codice ORDER BY r.codice""")
    st.dataframe(df, use_container_width=True)
    if not df.empty:
        st.download_button("Scarica Excel Customer Connect", excel_bytes({"Customer Connect": df}), "customer_connect.xlsx")

elif menu == "Ordini e chiusure":
    
    if st.session_state.get("ruolo") != "Admin":
        st.error("Area riservata Admin.")
        st.stop()

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
                c.commit(); cloud_backup_now(); c.close(); st.success("Importato")
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
                c.commit(); cloud_backup_now(); c.close(); st.success("Importato")
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
                c.commit(); cloud_backup_now(); c.close(); st.success("Importato")

elif menu == "Riconciliazione":
    
    if st.session_state.get("ruolo") != "Admin":
        st.error("Area riservata Admin.")
        st.stop()

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

elif menu == "Anomalie":
    
    if st.session_state.get("ruolo") != "Admin":
        st.error("Area riservata Admin.")
        st.stop()

    st.title("Anomalie")
    st.dataframe(q("SELECT * FROM anomalie ORDER BY id DESC"), use_container_width=True)


elif menu == "Gestione dati":
    admin_only()
    st.title("🛠️ Gestione dati")
    st.write("Modifica, aggiungi o elimina dati già inseriti. Usare con attenzione.")
    tables = [
        "clienti", "alias_strutture", "agenti", "magazzino",
        "offerte_header", "offerte_clienti", "offerte_prezzi",
        "interventi", "righe_intervento", "ddt", "ddt_righe",
        "order_history", "order_details", "chiusure", "anomalie"
    ]
    table = st.selectbox("Tabella", tables)
    editable_table(table, f"Gestione {table}")

elif menu == "Export completo":
    
    if st.session_state.get("ruolo") != "Admin":
        st.error("Area riservata Admin.")
        st.stop()

    st.title("Export completo")
    tables = ["clienti","alias_strutture","agenti","magazzino","offerte_header","offerte_clienti","offerte_prezzi","interventi","righe_intervento","ddt","ddt_righe","order_history","order_details","chiusure","anomalie"]
    sheets = {t: q(f"SELECT * FROM {t}") for t in tables}
    st.download_button("Scarica backup completo", excel_bytes(sheets), "orthoflow_backup_completo.xlsx")
