import os
import re
from hashlib import sha256
from io import BytesIO
from datetime import date, datetime
from pathlib import Path
from functools import lru_cache

import pandas as pd
import streamlit as st
from supabase import create_client

try:
    from ai_ocr import ai_enabled, ai_status, analyze_document, normalize_ai_items
except Exception:
    ai_enabled = lambda: False
    ai_status = lambda: {"enabled": False, "missing": ["OCR AI non disponibile"], "model": ""}
    analyze_document = None
    normalize_ai_items = lambda x: []

st.set_page_config(page_title="Scarico Sala AI · OrthoFlow", page_icon="📸", layout="wide")


def secret(name, default=None):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.getenv(name, default)


@st.cache_resource
def client():
    url = secret("SUPABASE_URL")
    key = secret("SUPABASE_SERVICE_KEY") or secret("SUPABASE_ANON_KEY") or secret("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("Supabase non configurato nei Secrets")
    return create_client(str(url).rstrip("/"), str(key))


def sb(): return client()
def generate_implant_document(intervention_id, header):
    """Genera un DDT di avvenuto impianto nello stile operativo Business."""
    try:
        existing=sb().table("documenti_impianto").select("*").eq("intervento_id",intervention_id).limit(1).execute().data or []
        if existing: return existing[0]
        division="PROTESICA" if "PROTES" in clean(header.get("linea")).upper() else "TRAUMA"
        nr=sb().rpc("prossimo_numero_documento_impianto",{"p_divisione":division}).execute().data
        year=pd.Timestamp(header.get("data_intervento")).year
        numero=f"{'PRO' if division=='PROTESICA' else 'TRA'}-{year}-{int(nr):06d}"
        rows=sb().table("righe_intervento").select("codice,descrizione,lotto,scadenza,quantita").eq("intervento_id",intervention_id).execute().data or []
        from io import BytesIO
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.enums import TA_CENTER
        buf=BytesIO(); styles=getSampleStyleSheet()
        styles["Title"].alignment=TA_CENTER
        doc=SimpleDocTemplate(buf,pagesize=A4,rightMargin=22,leftMargin=22,topMargin=22,bottomMargin=22)
        cc=clean(header.get("cartella_clinica")); dt=clean(header.get("data_intervento"))
        story=[Paragraph("<b>P.M. MEDICAL SRLS</b>",styles["Title"]),
          Paragraph("DOCUMENTO DI AVVENUTO IMPIANTO",styles["Heading2"]),Spacer(1,8)]
        info=[
          ["Destinatario / Struttura",clean(header.get("cliente")),"Tipo documento","D.D.T. AVVENUTO IMPIANTO"],
          ["Cod. Cliente",clean(header.get("codice_cliente")),"Numero doc.",numero],
          ["Cartella clinica",cc,"Data documento",dt],
          ["Divisione",division,"Causale",f"AVVENUTO IMPIANTO {division}"]]
        ti=Table(info,colWidths=[90,180,85,180])
        ti.setStyle(TableStyle([("GRID",(0,0),(-1,-1),.35,colors.grey),("BACKGROUND",(0,0),(0,-1),colors.lightgrey),("BACKGROUND",(2,0),(2,-1),colors.lightgrey),("FONTSIZE",(0,0),(-1,-1),8),("VALIGN",(0,0),(-1,-1),"MIDDLE")]))
        story += [ti,Spacer(1,12)]
        data=[["Cod. articolo","Descrizione","LOTTO","DATA SC","UM","QUANTITA'"]]
        for r in rows:
            data.append([clean(r.get("codice")),clean(r.get("descrizione")),clean(r.get("lotto")),clean(r.get("scadenza")),"PZ",str(r.get("quantita") or "")])
        tb=Table(data,repeatRows=1,colWidths=[75,205,75,70,35,55])
        tb.setStyle(TableStyle([("GRID",(0,0),(-1,-1),.35,colors.grey),("BACKGROUND",(0,0),(-1,0),colors.lightgrey),("FONTSIZE",(0,0),(-1,-1),7.5),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),3),("RIGHTPADDING",(0,0),(-1,-1),3)]))
        story += [tb,Spacer(1,14),
          Table([["Causale del Trasporto",f"AVVENUTO IMPIANTO {division}"],["Note",f"cc {cc} del {dt}"]],colWidths=[130,385],style=TableStyle([("GRID",(0,0),(-1,-1),.35,colors.grey),("BACKGROUND",(0,0),(0,-1),colors.lightgrey),("FONTSIZE",(0,0),(-1,-1),8)])),
          Spacer(1,22),Paragraph("Firma destinatario per accettazione: ____________________________________",styles["Normal"]),
          Spacer(1,18),Paragraph("Documento generato da OrthoFlow in attesa dell'integrazione con Business.",styles["Italic"])]
        doc.build(story); buf.seek(0)
        path=f"documenti_impianto/{division.lower()}/{year}/{numero}.pdf"
        sb().storage.from_("orthoflow-impianti").upload(path,buf.getvalue(),file_options={"content-type":"application/pdf","upsert":"true"})
        rec={"intervento_id":intervention_id,"divisione":division,"numero_documento":numero,"data_documento":header.get("data_intervento"),"storage_path":path}
        return sb().table("documenti_impianto").insert(rec).execute().data[0]
    except Exception as e:
        st.warning(f"Intervento salvato, ma documento impianto da rigenerare: {e}")
        return None


def clean(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()
def role(): return str(st.session_state.get("ruolo", "")).strip()
def user(): return str(st.session_state.get("user", "")).strip()
def ncode(v): return re.sub(r"[^A-Z0-9]", "", clean(v).upper())


if not user():
    st.warning("Accedi prima a OrthoFlow Control Tower.")
    st.stop()


def collect_scarico_files(saved, uploaded):
    result = dict(saved)
    for doc in uploaded or []:
        data = doc.getvalue()
        file_id = sha256(data).hexdigest()
        if file_id not in result:
            result[file_id] = {"name": doc.name, "data": data, "type": getattr(doc, "type", "") or ""}
    return result


def save_local(upload, category="scarico_sala"):
    base = Path("uploads") / category
    base.mkdir(parents=True, exist_ok=True)
    name = str(getattr(upload, "name", "foto_sala.jpg") or "foto_sala.jpg").replace("/", "_").replace("\\", "_")
    path = base / f"{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S_%f')}_{name}"
    path.write_bytes(upload.getvalue() if hasattr(upload, "getvalue") else upload.getbuffer())
    return str(path)


def save_camera(camera):
    base = Path("uploads") / "scarico_sala"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S_%f')}_camera.jpg"
    path.write_bytes(camera.getvalue())
    return str(path)


def storage_upload(local_path, intervention_id):
    bucket = "orthoflow-impianti"
    safe_name = Path(local_path).name
    storage_path = f"impianti/{pd.Timestamp.now().strftime('%Y/%m')}/intervento_{intervention_id}_{safe_name}"
    try:
        data = Path(local_path).read_bytes()
        if str(local_path).lower().endswith(".pdf") and data[:5] != b"%PDF-":
            raise ValueError("Il file dichiarato PDF non contiene un PDF valido")
        try:
            sb().storage.from_(bucket).upload(storage_path, data, file_options={"upsert": "true"})
        except Exception:
            sb().storage.from_(bucket).update(storage_path, data, file_options={"upsert": "true"})
        return bucket, storage_path
    except Exception:
        return "", ""


def table_df(table, order="id", desc=False):
    try:
        return pd.DataFrame(sb().table(table).select("*").order(order, desc=desc).execute().data or [])
    except Exception:
        return pd.DataFrame()


def client_options():
    d = table_df("clienti", "descrizione")
    out = []
    for _, r in d.iterrows():
        code = clean(r.get("codice_cliente"))
        desc = clean(r.get("descrizione") or r.get("descrizione_cliente"))
        if code or desc:
            out.append({"codice_cliente": code, "descrizione": desc, "label": f"{desc} ({code})" if code else desc})
    return out


def warehouse_labels():
    d = table_df("magazzini", "id")
    labels = []
    for _, r in d.iterrows():
        code = clean(r.get("codice_magazzino") or r.get("codice") or r.get("magazzino"))
        name = clean(r.get("nome_magazzino") or r.get("descrizione") or r.get("nome"))
        if code:
            labels.append(f"{code} - {name or code}")
    return labels or ["MAG1 - Magazzino 1"]


def agent_options():
    if role() == "Agente":
        a = clean(st.session_state.get("agente_nome"))
        return [a] if a else [user()]
    d = table_df("agenti", "nome")
    if not d.empty and "nome" in d.columns:
        vals = [clean(x) for x in d["nome"].tolist() if clean(x)]
        if vals:
            return vals
    return [""]


@lru_cache(maxsize=None)
def offer_ids_for(customer_code, line):
    try:
        links = (sb().table("offerte_clienti").select("offerta_id")
                 .eq("codice_cliente", customer_code).execute().data or [])
        out = []
        for link in links:
            oid = link.get("offerta_id")
            heads = (sb().table("offerte_header").select("id,linea")
                     .eq("id", oid).limit(1).execute().data or [])
            if heads and clean(heads[0].get("linea")).upper() == clean(line).upper():
                out.append(oid)
        return out
    except Exception:
        return []


# Queste cache vengono ricreate ad ogni rerun, dopo i controlli di accesso.
# Nessun prezzo viene condiviso tra sessioni o conservato in session_state.
@lru_cache(maxsize=None)
def offer_prices_for(oid):
    try:
        exact = {}
        insensitive = {}
        normalized = {}
        offset = 0
        while True:
            rows = (sb().table("offerte_prezzi").select("codice,prezzo")
                    .eq("offerta_id", oid).order("id")
                    .range(offset, offset + 499).execute().data or [])
            if not rows:
                break
            for row in rows:
                code = row.get("codice")
                if code is None:
                    continue
                code = str(code)
                exact.setdefault(code, row.get("prezzo"))
                insensitive.setdefault(code.upper(), row.get("prezzo"))
                key = ncode(code)
                if key:
                    normalized.setdefault(key, row.get("prezzo"))
            # Avanza della quantità ricevuta anche se il server limita la pagina.
            offset += len(rows)
        return exact, insensitive, normalized
    except Exception:
        # Non usare dati parziali e non ripetere una query fallita per ogni riga.
        return None


@lru_cache(maxsize=None)
def price_for(customer_code, product_code, line):
    target = clean(product_code).upper()
    if not target:
        return None
    try:
        for oid in offer_ids_for(customer_code, line):
            prices = offer_prices_for(oid)
            if prices is None:
                return None
            exact, insensitive, normalized = prices
            if target in exact:
                return float(exact[target] or 0)
            if target in insensitive:
                return float(insensitive[target] or 0)
            key = ncode(target)
            if key and key in normalized:
                return float(normalized[key] or 0)
    except Exception:
        pass
    return None


def manual_price_key(customer_code, code, line):
    return f"{clean(customer_code)}_{clean(line).upper()}_{ncode(code)}"


def manual_price_for(customer_code, code, line):
    try:
        key=manual_price_key(customer_code, code, line)
        if st.session_state.get(f"free_goods_{key}", False):
            return 0.0
        val = float(st.session_state.get(f"manual_price_{key}", 0) or 0)
        return val if val > 0 else None
    except Exception:
        return None


@lru_cache(maxsize=None)
def remembered_prices_for(customer_code, line):
    # La memoria deriva esclusivamente da prezzi manuali realmente salvati.
    try:
        rows = sb().rpc("prezzi_manuali_struttura", {
            "p_codice_cliente": clean(customer_code),
            "p_linea": clean(line).upper(),
        }).execute().data or []
        return {r["codice_normalizzato"]: float(r["prezzo"]) for r in rows}
    except Exception as e:
        st.warning(f"Prezzi manuali precedenti non disponibili: {e}")
        return {}


def remembered_price_for(customer_code, product_code, line):
    return remembered_prices_for(customer_code, line).get(ncode(product_code))


def available_qty(mag, code, lot):
    """Pre-check UX. La verifica definitiva e bloccante avviene nella RPC atomica."""
    try:
        rows = (sb().table("giacenze").select("codice,lotto,quantita,origine")
                .eq("codice_magazzino", mag).eq("lotto", lot).eq("origine", "CONTO DEPOSITO")
                .execute().data or [])
        return sum(float(r.get("quantita") or 0) for r in rows if ncode(r.get("codice")) == ncode(code))
    except Exception:
        return 0.0


def is_other_manufacturer(value):
    """Leghe e produttori ignoti non sono prova di materiale non J&J."""
    name = ncode(value)
    return any(brand in name for brand in (
        "STRYKER", "ZIMMER", "BIOMET", "MEDTRONIC",
        "SMITHNEPHEW", "SMITHANDNEPHEW", "ARTHREX", "BBRAUN", "AESCULAP", "INOMED"))


def run_ai(path, documents=None):
    if not ai_enabled():
        st.error("OCR AI non configurato. Verifica OPENAI_API_KEY ed ENABLE_AI_OCR nei Secrets.")
        return
    try:
        documents = documents or [{"path": path, "name": Path(path).name,
                                   "type": st.session_state.get("scarico_file_type", "")}]
        combined_rows, meta = [], {}
        with st.spinner(f"Analisi AI di {len(documents)} file: codici, lotti e scadenze…"):
            for document in documents:
                incoming = analyze_document(document["path"], mode="scarico_sala")
                combined_rows.extend(normalize_ai_items(incoming))
                for field, value in incoming.items():
                    if field != "items" and not meta.get(field) and value:
                        meta[field] = value
        meta["items"] = combined_rows
        st.session_state["scarico_ai_rows"] = combined_rows
        st.session_state["scarico_documents"] = documents
        st.session_state["scarico_editor_revision"] = int(st.session_state.get("scarico_editor_revision", 0)) + 1
        st.session_state["scarico_ai_meta"] = meta
        st.session_state["scarico_file_path"] = path
        st.session_state["scarico_file_name"] = Path(path).name
        st.session_state["scarico_source"] = "AI"
        st.session_state.pop("scarico_missing_prices", None)
        st.session_state.pop("scarico_stock_errors", None)
        st.success(f"AI completata: {len(st.session_state['scarico_ai_rows'])} righe rilevate.")
        st.rerun()
    except Exception as e:
        st.error(f"Errore analisi AI: {e}")


def save_document_after_transaction(intervention_id, procedure_date, customer_code, customer_name, agent, clinical_record):
    documents = st.session_state.get("scarico_documents") or [{
        "path": st.session_state.get("scarico_file_path"),
        "name": st.session_state.get("scarico_file_name"),
        "type": st.session_state.get("scarico_file_type", "")}]
    results = [
        save_one_document(intervention_id, procedure_date, customer_code, customer_name, agent, clinical_record, document)
        for document in documents]
    return all(results)


def save_one_document(intervention_id, procedure_date, customer_code, customer_name, agent, clinical_record, document):
    local_path = document.get("path")
    if not local_path or not Path(local_path).exists():
        return True
    bucket, storage_path = storage_upload(local_path, intervention_id)
    try:
        sb().table("documenti_impianto").insert({
            "intervento_id": str(intervention_id),
            "data_intervento": procedure_date.isoformat(),
            "codice_cliente": customer_code,
            "cliente": customer_name,
            "agente": clean(agent),
            "cartella_clinica": clean(clinical_record),
            "nome_file": document.get("name") or Path(local_path).name,
            "tipo_file": document.get("type", ""),
            "percorso_file": local_path,
            "storage_bucket": bucket,
            "storage_path": storage_path,
            "note": "Documento originale acquisito da Scarico Sala AI",
        }).execute()
        return True
    except Exception:
        return False


st.title("📸 Scarico Sala AI")
st.caption("Foto/PDF → verifica → intervento e scarico MAG1. Intervento, righe e movimenti vengono salvati in un'unica transazione: o riesce tutto oppure non viene scritto nulla.")
status = ai_status()
if status.get("enabled"):
    st.success(f"OCR AI attivo · {status.get('model', '')}")
else:
    st.warning("OCR AI non attivo: " + ", ".join(status.get("missing", [])))

camera_tab, upload_tab = st.tabs(["📷 Scatta foto con AI", "📄 Carica foto / PDF"])
with camera_tab:
    st.subheader("Fotografa etichette e foglio di scarico")
    st.info("Inquadra bene REF/codice, LOT/lotto e scadenza. Puoi fotografare il foglio con più etichette.")
    camera = st.camera_input("Scatta foto", key="scarico_camera_ai")
    if camera is not None:
        st.image(camera, use_container_width=True)
        if st.button("🤖 Analizza foto e crea lista codici", type="primary", use_container_width=True, key="analyze_camera"):
            st.session_state["scarico_file_type"] = "image/jpeg"
            run_ai(save_camera(camera))

with upload_tab:
    upload_revision = int(st.session_state.get("scarico_upload_revision", 0))
    uploads = st.file_uploader(
        "Carica foto o PDF scarico sala", type=["jpg", "jpeg", "png", "webp", "pdf"],
        accept_multiple_files=True, key=f"scarico_upload_ai_v2_{upload_revision}",
        help="Seleziona più file con Ctrl (Cmd su Mac) oppure aggiungili in più passaggi. Solo foto dello stesso intervento.")
    pending = collect_scarico_files(st.session_state.get("scarico_pending_files", {}), uploads)
    st.session_state["scarico_pending_files"] = pending
    if pending:
        st.caption(f"{len(pending)} file pronti. Le nuove selezioni si aggiungono alla lista.")
        if st.button("➕ Aggiungi altre foto o PDF", key="scarico_add_files", use_container_width=True):
            st.session_state["scarico_upload_revision"] = upload_revision + 1
            st.rerun()
        for file_id, entry in pending.items():
            label, action = st.columns([5, 1])
            label.write(f"📎 {entry['name']} · {len(entry['data']) / 1024:.0f} KB")
            if action.button("Rimuovi", key=f"scarico_remove_{file_id}"):
                st.session_state["scarico_pending_files"] = {k: v for k, v in pending.items() if k != file_id}
                st.session_state["scarico_upload_revision"] = upload_revision + 1
                st.rerun()
        if st.button("🧹 Svuota file selezionati", key="scarico_clear_files"):
            st.session_state["scarico_pending_files"] = {}
            st.session_state["scarico_upload_revision"] = upload_revision + 1
            st.rerun()
        with st.expander("Anteprima foto"):
            for entry in pending.values():
                if not entry["name"].lower().endswith(".pdf"):
                    st.image(entry["data"], caption=entry["name"], use_container_width=True)
        if st.button("🤖 Analizza tutti i file e crea lista codici", type="primary", use_container_width=True, key="analyze_upload"):
            documents = []
            for entry in pending.values():
                upload = BytesIO(entry["data"])
                upload.name = entry["name"]
                documents.append({"path": save_local(upload), "name": entry["name"], "type": entry["type"]})
            run_ai(documents[0]["path"], documents=documents)

meta = st.session_state.get("scarico_ai_meta", {}) or {}
source_rows = st.session_state.get("scarico_ai_rows", []) or []
excluded_indices = [i for i, r in enumerate(source_rows) if is_other_manufacturer(r.get("produttore"))]
restored_indices = []
if excluded_indices:
    restored_indices = st.multiselect(
        "Conferma e reinserisci materiale nostro / J&J escluso",
        excluded_indices,
        format_func=lambda i: f"{clean(source_rows[i].get('codice'))} · lotto {clean(source_rows[i].get('lotto'))} · {clean(source_rows[i].get('produttore'))}",
        key=f"scarico_restore_{st.session_state.get('scarico_editor_revision', 0)}",
        help="Seleziona le righe dopo aver verificato l'etichetta, prima di correggere la tabella.")
excluded_rows = [r for i, r in enumerate(source_rows) if i in excluded_indices and i not in restored_indices]
rows = [{**r, "jnj_verificato_manualmente": i in restored_indices}
        for i, r in enumerate(source_rows) if i not in excluded_indices or i in restored_indices]
clients = client_options()
ai_clinic = clean(meta.get("clinic_name"))
if clients:
    default_idx = 0
    if ai_clinic:
        for i, c in enumerate(clients):
            if ai_clinic.casefold() in c["descrizione"].casefold() or c["descrizione"].casefold() in ai_clinic.casefold():
                default_idx = i
                break
    selected_client = st.selectbox("Struttura / cliente", clients, index=default_idx, format_func=lambda x: x["label"])
else:
    selected_client = {"codice_cliente": "", "descrizione": st.text_input("Struttura / cliente", value=ai_clinic)}


line = st.selectbox("Linea", ["TRAUMA", "PROTESICA", "CMF", "SPINE", "SPORTS", "ALTRO"], key="scarico_price_line")
is_malzoni = clean(selected_client.get("codice_cliente")) == "9010013"
if source_rows:
    st.caption(f"OCR: {len(source_rows)} righe riconosciute · {len(rows)} righe nella lista modificabile · {len(excluded_rows)} righe di altri produttori escluse.")
if excluded_rows:
    st.warning(f"{len(excluded_rows)} righe di altri produttori escluse dallo scarico, dal fatturato e dagli ordini OrthoFlow.")
    with st.expander("Materiale di altre aziende escluso"):
        st.dataframe(pd.DataFrame(excluded_rows), use_container_width=True, hide_index=True)
with st.form("scarico_ai_confirm"):
    if rows:
        st.divider()
        st.subheader("✅ Lista materiali riconosciuti")
        st.caption("Tocca una cella per correggere codice, lotto, scadenza o quantità. Spunta Escludi riga per non inserirla nello scarico. Le modifiche vengono applicate alla conferma.")
        df_rows = pd.DataFrame(rows)
        preferred = ["codice", "jnj_verificato_manualmente", "escludi_riga", "descrizione", "lotto", "scadenza", "quantita", "produttore", "confidence", "warning"]
        df_rows["escludi_riga"] = False
        for col in preferred:
            if col not in df_rows.columns:
                df_rows[col] = ""
        if is_malzoni:
            if "conto_deposito_struttura" not in df_rows.columns:
                df_rows["conto_deposito_struttura"] = False
            df_rows["conto_deposito_struttura"] = df_rows["conto_deposito_struttura"].fillna(False).astype(bool)
            preferred.insert(1, "conto_deposito_struttura")
            st.info("Malzoni: spunta il materiale della struttura Smart Track. Prezzi, fatturato e ordini restano inclusi; queste righe non scaricano la vostra giacenza.")
        edited = st.data_editor(
            df_rows[preferred], num_rows="dynamic", use_container_width=True,
            height=min(1600, max(220, 35 * (len(df_rows) + 3))), row_height=35,
            column_config={
                "jnj_verificato_manualmente": None,
                "escludi_riga": st.column_config.CheckboxColumn(
                    "Escludi riga", default=False,
                    help="La riga non verrà salvata e non genererà fatturato, ordini o movimenti di magazzino."),
                "codice": st.column_config.TextColumn("Codice Johnson/REF"),
                "lotto": st.column_config.TextColumn("Lotto"),
                "conto_deposito_struttura": st.column_config.CheckboxColumn(
                "Conto deposito struttura", default=False,
                help="Materiale Malzoni / Smart Track: incluso nel fatturato, senza scarico del nostro magazzino.")},
            key=f"scarico_ai_editor_{clean(selected_client.get('codice_cliente'))}_{st.session_state.get('scarico_editor_revision', 0)}")
        # Mantieni immutabile la base OCR: Streamlit applica le modifiche tramite lo stato del widget.
        warnings = [clean(r.get("warning")) for r in edited.to_dict("records") if clean(r.get("warning"))]
        if warnings:
            with st.expander("⚠️ Avvisi AI"):
                for w in warnings:
                    st.write("•", w)

    st.divider()
    st.subheader("🏥 Dati intervento e conferma scarico")
    warehouses = warehouse_labels()
    agents = agent_options()
    ai_clinic = clean(meta.get("clinic_name"))
    ai_record = clean(meta.get("clinical_record"))
    ai_date = pd.to_datetime(meta.get("procedure_date"), errors="coerce") if meta.get("procedure_date") else pd.NaT
    ai_surgeon = clean(meta.get("surgeon"))

    missing_prices = st.session_state.get("scarico_missing_prices", []) or []
    can_manage_prices = str(st.session_state.get("role","")).strip().lower() in ["admin","amministrazione"] or "DIREZIONE" in (st.session_state.get("permessi") or []) or "AMMINISTRAZIONE" in (st.session_state.get("permessi") or [])
    if missing_prices and can_manage_prices:
        st.warning("Alcuni codici non hanno un prezzo nell'offerta collegata. Inserisci il prezzo manuale prima di confermare lo scarico.")
        with st.expander("💶 Prezzi mancanti da inserire", expanded=True):
            # One price input per unique code. The same REF can appear on multiple lots/rows.
            seen_price_codes = set()
            for item in missing_prices:
                code = clean(item.get("codice"))
                code_key = ncode(code)
                if not code_key or code_key in seen_price_codes:
                    continue
                seen_price_codes.add(code_key)
                cols = st.columns([2, 4, 2, 2])
                cols[0].markdown(f"**{code}**")
                cols[1].caption(clean(item.get("descrizione")) or "Descrizione non disponibile")
                cols[2].number_input("Prezzo €", min_value=0.0, step=0.01, format="%.2f", key=f"manual_price_{manual_price_key(selected_client.get('codice_cliente'), code, line)}", label_visibility="collapsed")
                cols[3].checkbox("Sconto merce €0", key=f"free_goods_{manual_price_key(selected_client.get('codice_cliente'), code, line)}", help="Usa prezzo zero come valore reale, non come prezzo mancante.")

    stock_errors = st.session_state.get("scarico_stock_errors", []) or []
    if stock_errors:
        st.warning("Uno o più codici/lotti nostri non hanno quantità sufficiente: saranno segnalati a Direzione. Le righe conto deposito struttura sono escluse da questo controllo.")
        st.dataframe(pd.DataFrame(stock_errors), use_container_width=True, hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        procedure_date = st.date_input("Data intervento", value=ai_date.date() if pd.notna(ai_date) else date.today())
        clinical_record = st.text_input("Numero cartella clinica", value=ai_record)
        surgeon = st.text_input("Chirurgo", value=ai_surgeon)
    with c2:
        wh = st.selectbox("Scarica da giacenza", warehouses)
        mag = wh.split(" - ")[0]
        agent = st.selectbox("Agente", agents) if agents and agents != [""] else st.text_input("Agente")

    verified = st.checkbox("Ho verificato codice Johnson/REF, lotto, scadenza e quantità di tutte le righe.")
    confirm = st.form_submit_button("📤 Crea intervento e scarica materiali", type="primary", use_container_width=True, disabled=(len(rows) == 0))

if confirm:
    if not verified:
        st.error("Conferma di aver verificato i materiali prima di creare l’intervento.")
        st.stop()
    final_rows = edited.to_dict("records") if rows else []
    valid_rows = []
    for r in final_rows:
        if r.get("escludi_riga") is True:
            continue
        if is_other_manufacturer(r.get("produttore")) and not r.get("jnj_verificato_manualmente", False):
            continue
        code = clean(r.get("codice")).upper()
        lot = clean(r.get("lotto"))
        try:
            qty = float(r.get("quantita") or 1)
        except Exception:
            qty = 0
        if code and lot and qty > 0:
            valid_rows.append((r, code, lot, qty))

    if not valid_rows:
        st.error("Nessuna riga valida: servono almeno codice, lotto e quantità > 0.")
        st.stop()

    # UX pre-flight: raggruppa duplicati. La RPC ripete il controllo con lock DB ed è quella autoritativa.
    requested = {}
    for r, code, lot, qty in valid_rows:
        if is_malzoni and bool(r.get("conto_deposito_struttura", False)):
            continue
        key = (ncode(code), lot)
        requested[key] = requested.get(key, 0.0) + qty
    shortages = []
    for (norm_code, lot), qty in requested.items():
        sample_code = next(code for _, code, l, _ in valid_rows if ncode(code) == norm_code and l == lot)
        avail = available_qty(mag, sample_code, lot)
        if avail < qty:
            shortages.append({"Codice": sample_code, "Lotto": lot, "Disponibile": avail, "Richiesto": qty, "Magazzino": mag})
    if shortages:
        st.session_state["scarico_stock_errors"] = shortages
    else:
        st.session_state.pop("scarico_stock_errors", None)

    customer_code = clean(selected_client.get("codice_cliente"))
    priced_rows = []
    missing = []
    for r, code, lot, qty in valid_rows:
        price = price_for(customer_code, code, line)
        source = "OFFERTA"
        if price is None:
            price = manual_price_for(customer_code, code, line)
            source = ("SCONTO_MERCE" if st.session_state.get(f"free_goods_{manual_price_key(customer_code, code, line)}", False) else "MANUALE") if price is not None else "MANCANTE"
        if price is None:
            price = remembered_price_for(customer_code, code, line)
            if price is not None:
                source = "MANUALE_MEMORIZZATO"
        if price is None:
            missing.append({"codice": code, "descrizione": clean(r.get("descrizione"))})
            price = 0.0
            source = "DA_VERIFICARE_DIREZIONE"
        priced_rows.append((r, code, lot, qty, price, source))

    if missing:
        st.session_state["scarico_missing_prices"] = missing
        if can_manage_prices:
            st.warning(f"{len(missing)} prezzi mancanti: lo scarico può proseguire a €0 provvisorio oppure puoi regolarizzarli ora.")
    else:
        st.session_state.pop("scarico_missing_prices", None)

    rpc_rows = []
    for r, code, lot, qty, price, price_source in priced_rows:
        manufacturer = clean(r.get("produttore"))
        validation = "J&J verificato manualmente" if r.get("jnj_verificato_manualmente", False) else "Validato J&J" if any(x in manufacturer.upper() for x in ["JOHNSON", "J&J", "DEPUY", "SYNTHES"]) else ("Marchio non letto" if not manufacturer else "Prodotto non J&J")
        rpc_rows.append({
            "codice": code,
            "descrizione": clean(r.get("descrizione")),
            "lotto": lot,
            "scadenza": clean(r.get("scadenza")) or None,
            "quantita": qty,
            "produttore": manufacturer,
            "validazione": validation,
            "prezzo": float(price),
            "prezzo_source": price_source,
            "conto_deposito_struttura": is_malzoni and bool(r.get("conto_deposito_struttura", False)),
        })

    header = {
        "data_intervento": procedure_date.isoformat(),
        "codice_cliente": customer_code,
        "cliente": clean(selected_client.get("descrizione")),
        "struttura": clean(selected_client.get("descrizione")),
        "cartella_clinica": clean(clinical_record),
        "chirurgo": clean(surgeon),
        "agente": clean(agent),
        "linea": line,
        "magazzino_scarico": mag,
    }

    try:
        result = sb().rpc("crea_intervento_scarico_ai_flessibile", {
            "p_header": header,
            "p_rows": rpc_rows,
            "p_utente": user(),
        }).execute().data or {}
        intervention_id = result.get("intervento_id")
        inserted = int(result.get("righe", 0) or 0)
        total = float(result.get("totale", 0) or 0)

        # Se lo scarico proviene da un magazzino associato a un Kit, genera automaticamente i reintegri.
        try:
            kits = sb().table("kit_logistici").select("id,codice").eq("codice_magazzino", mag).execute().data or []
            if len(kits) == 1 and intervention_id:
                kit_id = int(kits[0]["id"])
                saved_rows = sb().table("righe_intervento").select("id,codice,lotto,quantita,origine").eq("intervento_id", intervention_id).execute().data or []
                for sr in saved_rows:
                    if sr.get("origine") == "CONTO DEPOSITO STRUTTURA":
                        continue
                    exists = sb().table("reintegri_kit").select("id").eq("kit_id", kit_id).eq("riga_intervento_id", sr["id"]).limit(1).execute().data or []
                    if not exists:
                        sb().table("reintegri_kit").insert({
                            "kit_id": kit_id,
                            "riga_intervento_id": sr["id"],
                            "codice": sr.get("codice"),
                            "lotto_consumato": sr.get("lotto"),
                            "quantita_richiesta": float(sr.get("quantita") or 0),
                            "stato": "DA_REINTEGRARE",
                            "utente": user()
                        }).execute()
                st.info(f"Kit {kits[0]['codice']}: creati automaticamente i reintegri dei componenti utilizzati.")
            elif len(kits) > 1:
                st.warning("Più Kit risultano associati allo stesso magazzino: reintegro automatico non creato per evitare un abbinamento errato.")
        except Exception as kit_err:
            st.warning(f"Scarico completato, ma generazione reintegro Kit da verificare: {kit_err}")

        doc_ok = save_document_after_transaction(
            intervention_id, procedure_date, customer_code,
            clean(selected_client.get("descrizione")), agent, clinical_record
        )
        st.success(f"Intervento {intervention_id} creato in modo atomico. Righe registrate: {inserted}. Fatturato teorico: € {total:,.2f}")
        if not doc_ok:
            st.warning("Intervento e magazzino sono stati salvati correttamente, ma il documento originale non è stato archiviato. Puoi ricaricarlo dall'Archivio impianti.")

        for k in ["scarico_pending_files", "scarico_documents", "scarico_ai_rows", "scarico_ai_meta", "scarico_file_path", "scarico_file_name", "scarico_file_type", "scarico_source", "scarico_missing_prices", "scarico_stock_errors", "scarico_verified"]:
            st.session_state.pop(k, None)
        for k in list(st.session_state.keys()):
            if str(k).startswith("manual_price_") or str(k).startswith("free_goods_"):
                st.session_state.pop(k, None)
        st.session_state["scarico_editor_revision"] = int(st.session_state.get("scarico_editor_revision", 0)) + 1
        st.session_state["scarico_upload_revision"] = int(st.session_state.get("scarico_upload_revision", 0)) + 1
        st.cache_data.clear()
    except Exception as e:
        msg = str(e)
        if "GIACENZA_INSUFFICIENTE" in msg:
            st.error("Giacenza modificata o insufficiente al momento della conferma. La transazione è stata annullata: nessun intervento, riga o movimento è stato salvato.")
        else:
            st.error(f"Scarico non completato. La transazione è stata annullata: {e}")


