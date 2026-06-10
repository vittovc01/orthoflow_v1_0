
import streamlit as st
import pandas as pd
from datetime import date
from database import init_db, get_conn
from helpers import *
from ai_ocr import ai_enabled, analyze_image, normalize_ai_items
import json

st.set_page_config(page_title="OrthoFlow Control Tower v1.0", layout="wide")
init_db()

def q(sql, params=()):
    c = get_conn()
    df = pd.read_sql_query(sql, c, params=params)
    c.close()
    return df

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

menu = st.sidebar.radio("Menu", [
    "Dashboard",
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
    "Export completo"
])

if menu == "Dashboard":
    st.title("Dashboard")
    c = get_conn()
    metrics = {
        "Clienti": c.execute("SELECT COUNT(*) n FROM clienti").fetchone()["n"],
        "Righe magazzino": c.execute("SELECT COUNT(*) n FROM magazzino").fetchone()["n"],
        "Interventi": c.execute("SELECT COUNT(*) n FROM interventi").fetchone()["n"],
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

elif menu == "Loan Monitor":
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
                c.commit(); c.close()
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

elif menu == "Offerte":
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

elif menu == "DDT carico / Loan":
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
                    st.error("OCR AI non configurato. Imposta OPENAI_API_KEY e ENABLE_AI_OCR=true.")
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
        edited = st.data_editor(pd.DataFrame(rows), use_container_width=True, num_rows="dynamic")
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
elif menu == "Scarico sala":
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
            if st.button("Analizza con OCR AI"):
                if not ai_enabled():
                    st.error("OCR AI non configurato. Imposta OPENAI_API_KEY e ENABLE_AI_OCR=true nel file .env / variabili cloud.")
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
        edited = st.data_editor(df_ai, use_container_width=True, num_rows="dynamic")
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
elif menu == "Work Implant":
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

elif menu == "Riconciliazione":
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
    st.title("Anomalie")
    st.dataframe(q("SELECT * FROM anomalie ORDER BY id DESC"), use_container_width=True)

elif menu == "Export completo":
    st.title("Export completo")
    tables = ["clienti","agenti","magazzino","offerte_header","offerte_clienti","offerte_prezzi","interventi","righe_intervento","ddt","ddt_righe","order_history","order_details","chiusure","anomalie"]
    sheets = {t: q(f"SELECT * FROM {t}") for t in tables}
    st.download_button("Scarica backup completo", excel_bytes(sheets), "orthoflow_backup_completo.xlsx")
