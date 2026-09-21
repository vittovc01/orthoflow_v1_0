import os
import re
from datetime import date
from pathlib import Path

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


def offer_ids_for(customer_code, line):
    try:
        links = sb().table("offerte_clienti").select("offerta_id").eq("codice_cliente", customer_code).execute().data or []
        ids = []
        for link in links:
            oid = link.get("offerta_id")
            heads = sb().table("offerte_header").select("id,linea").eq("id", oid).limit(1).execute().data or []
            if heads and clean(heads[0].get("linea")).upper() == clean(line).upper():
                ids.append(oid)
        return ids
    except Exception:
        return []


def price_for(customer_code, product_code, line):
    target = clean(product_code).upper()
    if not target:
        return None
    try:
        for oid in offer_ids_for(customer_code, line):
            rows = (sb().table("offerte_prezzi").select("codice,prezzo")
                    .eq("offerta_id", oid).eq("codice", target).limit(1).execute().data or [])
            if rows:
                return float(rows[0].get("prezzo") or 0)
            rows = (sb().table("offerte_prezzi").select("codice,prezzo")
                    .eq("offerta_id", oid).ilike("codice", target).limit(20).execute().data or [])
            for p in rows:
                if ncode(p.get("codice")) == ncode(target):
                    return float(p.get("prezzo") or 0)
    except Exception:
        pass
    return None


def manual_price_for(code):
    try:
        val = float(st.session_state.get(f"manual_price_{ncode(code)}", 0) or 0)
        return val if val > 0 else None
    except Exception:
        return None


def available_qty(mag, code, lot):
    """Pre-check UX. La verifica definitiva e bloccante avviene nella RPC atomica."""
    try:
        rows = (sb().table("giacenze").select("codice,lotto,quantita,origine")
                .eq("codice_magazzino", mag).eq("lotto", lot).eq("origine", "CONTO DEPOSITO")
                .execute().data or [])
        return sum(float(r.get("quantita") or 0) for r in rows if ncode(r.get("codice")) == ncode(code))
    except Exception:
        return 0.0


def run_ai(path):
    if not ai_enabled():
        st.error("OCR AI non configurato. Verifica OPENAI_API_KEY ed ENABLE_AI_OCR nei Secrets.")
        return
    try:
        with st.spinner("Analisi AI di codici, lotti e scadenze…"):
            meta = analyze_document(path, mode="scarico_sala")
        st.session_state["scarico_ai_rows"] = normalize_ai_items(meta)
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
    local_path = st.session_state.get("scarico_file_path")
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
            "nome_file": st.session_state.get("scarico_file_name", Path(local_path).name),
            "tipo_file": st.session_state.get("scarico_file_type", ""),
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
    upload = st.file_uploader("Carica foto o PDF scarico sala", type=["jpg", "jpeg", "png", "webp", "pdf"], key="scarico_upload_ai")
    if upload is not None:
        path = save_local(upload)
        st.session_state["scarico_file_type"] = getattr(upload, "type", "") or ""
        if str(upload.name).lower().endswith(".pdf"):
            st.info(f"PDF pronto: {upload.name}")
        else:
            st.image(upload, use_container_width=True)
        if st.button("🤖 Analizza file e crea lista codici", type="primary", use_container_width=True, key="analyze_upload"):
            run_ai(path)

meta = st.session_state.get("scarico_ai_meta", {}) or {}
rows = st.session_state.get("scarico_ai_rows", []) or []
if rows:
    st.divider()
    st.subheader("✅ Lista materiali riconosciuti")
    st.caption("Controlla sempre codice Johnson/REF, lotto, scadenza e quantità prima della conferma.")
    df_rows = pd.DataFrame(rows)
    preferred = ["codice", "descrizione", "lotto", "scadenza", "quantita", "produttore", "confidence", "warning"]
    for col in preferred:
        if col not in df_rows.columns:
            df_rows[col] = ""
    edited = st.data_editor(df_rows[preferred], num_rows="dynamic", use_container_width=True, key="scarico_ai_editor")
    st.session_state["scarico_ai_rows"] = edited.to_dict("records")
    warnings = [clean(r.get("warning")) for r in st.session_state["scarico_ai_rows"] if clean(r.get("warning"))]
    if warnings:
        with st.expander("⚠️ Avvisi AI"):
            for w in warnings:
                st.write("•", w)

st.divider()
st.subheader("🏥 Dati intervento e conferma scarico")
clients = client_options()
warehouses = warehouse_labels()
agents = agent_options()
ai_clinic = clean(meta.get("clinic_name"))
ai_record = clean(meta.get("clinical_record"))
ai_date = pd.to_datetime(meta.get("procedure_date"), errors="coerce") if meta.get("procedure_date") else pd.NaT
ai_surgeon = clean(meta.get("surgeon"))

missing_prices = st.session_state.get("scarico_missing_prices", []) or []
if missing_prices:
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
            cols = st.columns([2, 4, 2])
            cols[0].markdown(f"**{code}**")
            cols[1].caption(clean(item.get("descrizione")) or "Descrizione non disponibile")
            cols[2].number_input("Prezzo €", min_value=0.0, step=0.01, format="%.2f", key=f"manual_price_{code_key}", label_visibility="collapsed")

stock_errors = st.session_state.get("scarico_stock_errors", []) or []
if stock_errors:
    st.error("Scarico bloccato: uno o più codici/lotti non hanno quantità sufficiente nel magazzino selezionato.")
    st.dataframe(pd.DataFrame(stock_errors), use_container_width=True, hide_index=True)

with st.form("scarico_ai_confirm"):
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

    c1, c2 = st.columns(2)
    with c1:
        procedure_date = st.date_input("Data intervento", value=ai_date.date() if pd.notna(ai_date) else date.today())
        clinical_record = st.text_input("Numero cartella clinica", value=ai_record)
        surgeon = st.text_input("Chirurgo", value=ai_surgeon)
    with c2:
        wh = st.selectbox("Scarica da giacenza", warehouses)
        mag = wh.split(" - ")[0]
        agent = st.selectbox("Agente", agents) if agents and agents != [""] else st.text_input("Agente")
        line = st.selectbox("Linea", ["TRAUMA", "PROTESICA", "CMF", "SPINE", "SPORTS", "ALTRO"])

    verified = st.checkbox("Ho verificato codice Johnson/REF, lotto, scadenza e quantità di tutte le righe.")
    confirm = st.form_submit_button("📤 Crea intervento e scarica materiali", type="primary", use_container_width=True, disabled=(not verified or len(st.session_state.get("scarico_ai_rows", [])) == 0))

if confirm:
    final_rows = st.session_state.get("scarico_ai_rows", []) or []
    valid_rows = []
    for r in final_rows:
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
    for _, code, lot, qty in valid_rows:
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
        st.error("Giacenza insufficiente: intervento NON creato e magazzino NON scaricato.")
        st.rerun()
    st.session_state.pop("scarico_stock_errors", None)

    customer_code = clean(selected_client.get("codice_cliente"))
    priced_rows = []
    missing = []
    for r, code, lot, qty in valid_rows:
        price = price_for(customer_code, code, line)
        source = "OFFERTA"
        if price is None:
            price = manual_price_for(code)
            source = "MANUALE" if price is not None else "MANCANTE"
        if price is None:
            missing.append({"codice": code, "descrizione": clean(r.get("descrizione"))})
        priced_rows.append((r, code, lot, qty, price, source))

    if missing:
        st.session_state["scarico_missing_prices"] = missing
        st.error(f"Mancano {len(missing)} prezzi. Inseriscili nel riquadro 'Prezzi mancanti da inserire' e premi di nuovo Crea intervento.")
        st.rerun()
    st.session_state.pop("scarico_missing_prices", None)

    rpc_rows = []
    for r, code, lot, qty, price, price_source in priced_rows:
        manufacturer = clean(r.get("produttore"))
        validation = "Validato J&J" if any(x in manufacturer.upper() for x in ["JOHNSON", "J&J", "DEPUY", "SYNTHES"]) else ("Marchio non letto" if not manufacturer else "Prodotto non J&J")
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
        })

    header = {
        "data_intervento": procedure_date.isoformat(),
        "codice_cliente": customer_code,
        "cliente": clean(selected_client.get("descrizione")),
        "cartella_clinica": clean(clinical_record),
        "chirurgo": clean(surgeon),
        "agente": clean(agent),
        "linea": line,
        "magazzino_scarico": mag,
    }

    try:
        result = sb().rpc("crea_intervento_scarico_ai", {
            "p_header": header,
            "p_rows": rpc_rows,
            "p_utente": user(),
        }).execute().data or {}
        intervention_id = result.get("intervento_id")
        inserted = int(result.get("righe", 0) or 0)
        total = float(result.get("totale", 0) or 0)

        doc_ok = save_document_after_transaction(
            intervention_id, procedure_date, customer_code,
            clean(selected_client.get("descrizione")), agent, clinical_record
        )
        st.success(f"Intervento {intervention_id} creato in modo atomico. Materiali scaricati: {inserted}. Fatturato teorico: € {total:,.2f}")
        if not doc_ok:
            st.warning("Intervento e magazzino sono stati salvati correttamente, ma il documento originale non è stato archiviato. Puoi ricaricarlo dall'Archivio impianti.")

        for k in ["scarico_ai_rows", "scarico_ai_meta", "scarico_file_path", "scarico_file_name", "scarico_file_type", "scarico_source", "scarico_missing_prices", "scarico_stock_errors", "scarico_verified"]:
            st.session_state.pop(k, None)
        for k in list(st.session_state.keys()):
            if str(k).startswith("manual_price_"):
                st.session_state.pop(k, None)
        st.cache_data.clear()
    except Exception as e:
        msg = str(e)
        if "GIACENZA_INSUFFICIENTE" in msg:
            st.error("Giacenza modificata o insufficiente al momento della conferma. La transazione è stata annullata: nessun intervento, riga o movimento è stato salvato.")
        else:
            st.error(f"Scarico non completato. La transazione è stata annullata: {e}")
