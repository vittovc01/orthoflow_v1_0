from clinic_matching import clinic_default_index
import os
import json
import copy
import re
from hashlib import sha256
from io import BytesIO
from datetime import date, datetime
from pathlib import Path
from functools import lru_cache
from uuid import uuid4
from ocr_review import build_review, aggregate_review, merge_confirmed_fields
from ocr_service import analyze_documents
from ocr_repository import OriginalDocument, SupabaseReviewRepository, without_images, load_catalog_codes

from ocr_runtime import current_label_pipeline
current_label_pipeline()
from label_pipeline import review_errors, inventory_errors, aggregate_labels, PIPELINE_VERSION, gs1_parse

import pandas as pd
import streamlit as st
from orthoflow_branding import configure_page
from document_compression import compress_document
from supabase import create_client

try:
    from ai_ocr import ai_enabled, ai_status, analyze_document, normalize_ai_items
except Exception:
    ai_enabled = lambda: False
    ai_status = lambda: {"enabled": False, "missing": ["OCR AI non disponibile"], "model": ""}
    analyze_document = None
    normalize_ai_items = lambda x: []

configure_page(page_title="Scarico Sala AI · P.M. Medical", page_icon="📸", layout="wide")


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
          Spacer(1,18),Paragraph("Documento generato da P.M. Medical in attesa dell'integrazione con Business.",styles["Italic"])]
        doc.build(story); buf.seek(0)
        path=f"documenti_impianto/{division.lower()}/{year}/{numero}.pdf"
        sb().storage.from_("orthoflow-impianti").upload(path,compress_document(buf.getvalue(), path).data,file_options={"content-type":"application/pdf","upsert":"true"})
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
    st.warning("Accedi prima a P.M. Medical Control Tower.")
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
        compressed = compress_document(Path(local_path).read_bytes(), local_path)
        data = compressed.data
        if str(local_path).lower().endswith(".pdf") and data[:5] != b"%PDF-":
            raise ValueError("Il file dichiarato PDF non contiene un PDF valido")
        try:
            sb().storage.from_(bucket).upload(storage_path, data, file_options={"upsert": "true", "content-type": compressed.content_type})
        except Exception:
            sb().storage.from_(bucket).update(storage_path, data, file_options={"upsert": "true", "content-type": compressed.content_type})
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
    """Pre-check UX; include null/empty lots only for confirmed lotless rows."""
    try:
        query = (sb().table("giacenze").select("codice,lotto,quantita,origine")
                 .eq("codice_magazzino", mag).eq("origine", "CONTO DEPOSITO").eq("codice", code))
        if lot:
            query = query.eq("lotto", lot)
        total, offset = 0.0, 0
        while True:
            batch = query.order("id").range(offset, offset + 499).execute().data or []
            total += sum(max(0.0, float(r.get("quantita") or 0)) for r in batch
                         if ncode(r.get("codice")) == ncode(code) and clean(r.get("lotto")) == lot)
            if len(batch) < 500:
                return total
            offset += 500
    except Exception:
        return 0.0


def is_other_manufacturer(value):
    """Leghe e produttori ignoti non sono prova di materiale non J&J."""
    name = ncode(value)
    return any(brand in name for brand in (
        "STRYKER", "ZIMMER", "BIOMET", "MEDTRONIC",
        "SMITHNEPHEW", "SMITHANDNEPHEW", "ARTHREX", "BBRAUN", "AESCULAP", "INOMED"))


def run_ai(path, documents=None, *, privacy_manifest=None):
    documents = documents or [{"path":path,"name":Path(path).name,"type":st.session_state.get("scarico_file_type", "")}]
    if privacy_manifest is None:
        from local_label_reader import prepare_document
        with st.spinner("Controllo locale dei ritagli e della qualità, senza invio al modello…"):
            proposals=[prepare_document(d["path"]) for d in documents]
        st.session_state["scarico_privacy_pending"]={"documents":documents,"proposals":proposals}
        st.rerun()
        return
    if not ai_enabled():
        st.error("OCR AI non configurato. Verifica OPENAI_API_KEY ed ENABLE_AI_OCR nei Secrets.")
        return
    try:
        documents = documents or [{"path": path, "name": Path(path).name,
                                   "type": st.session_state.get("scarico_file_type", "")}]
        originals = [OriginalDocument(d.get("name") or Path(d["path"]).name, Path(d["path"]).read_bytes()) for d in documents]
        with st.spinner(f"Analisi AI di {len(documents)} file: codici, lotti e scadenze…"):
            from gtin_catalog import supabase_lookup
            def approved_analyzer(source,mode):
                digest=sha256(Path(source).read_bytes()).hexdigest()
                return analyze_document(source,mode=mode,privacy_approval=privacy_manifest.get(digest))
            meta = analyze_documents(originals, analyzer=approved_analyzer,gtin_catalog=supabase_lookup(sb()))
            combined_rows = normalize_ai_items(meta)
        meta["physical_label_count"] = len(combined_rows)
        meta["items"] = combined_rows
        st.session_state.pop("scarico_audit_request", None)
        st.session_state["scarico_ai_rows"] = combined_rows
        st.session_state["scarico_ai_original_rows"] = copy.deepcopy(combined_rows)
        st.session_state["scarico_documents"] = documents
        st.session_state["scarico_editor_revision"] = int(st.session_state.get("scarico_editor_revision", 0)) + 1
        st.session_state["scarico_ai_meta"] = meta
        st.session_state["scarico_file_path"] = path
        st.session_state["scarico_file_name"] = Path(path).name
        st.session_state["scarico_source"] = "AI"
        st.session_state.pop("scarico_verified", None)
        st.session_state.pop("scarico_missing_prices", None)
        st.session_state.pop("scarico_stock_errors", None)
        st.info(f"Analisi terminata: {len(st.session_state['scarico_ai_rows'])} etichette proposte. Verifica completezza, campi e avvisi prima della conferma.")
        st.rerun()
    except Exception as e:
        st.error(f"Analisi non completata ({type(e).__name__}). Verifica connessione e configurazione senza condividere chiavi nei log.")


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
st.caption(f"Versione OCR disponibile: {PIPELINE_VERSION} · lettura per singola etichetta")
st.caption("Le etichette del produttore con REF e LOT rappresentano i materiali; gli adesivi interni di inventario non aumentano il conteggio.")
st.caption("Foto/PDF → verifica → intervento e scarico MAG1. Intervento, righe e movimenti vengono salvati in un'unica transazione: o riesce tutto oppure non viene scritto nulla.")
status = ai_status()
if status.get("enabled"):
    st.success(f"OCR AI attivo · {status.get('label_model', status.get('model', ''))}")
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
        with st.expander("Anteprima documenti (foto e PDF)", expanded=True):
            for file_id, entry in pending.items():
                st.caption(entry["name"])
                if entry["name"].lower().endswith(".pdf") or entry.get("type") == "application/pdf":
                    st.pdf(entry["data"], height=600, key=f"scarico_pdf_{file_id}", alt=entry["name"])
                else:
                    st.image(entry["data"], caption=entry["name"], use_container_width=True)
        if st.button("🤖 Analizza tutti i file e crea lista codici", type="primary", use_container_width=True, key="analyze_upload"):
            documents = []
            for entry in pending.values():
                upload = BytesIO(entry["data"])
                upload.name = entry["name"]
                documents.append({"path": save_local(upload), "name": entry["name"], "type": entry["type"]})
            run_ai(documents[0]["path"], documents=documents)


privacy_pending=st.session_state.get("scarico_privacy_pending")
if privacy_pending:
    from label_pipeline import render_pages,crop_region,decode_barcodes
    from image_quality import acquisition_report
    st.subheader("Verifica locale dei ritagli prima dell'invio")
    st.info("Al modello saranno inviati soltanto i ritagli selezionati qui sotto. Deseleziona qualsiasi ritaglio con intestazione, iniziali, numero di cartella o altri dati del paziente. Se manca un'etichetta, aggiungi una foto ravvicinata. I dati intervento andranno compilati manualmente.")
    selected={};all_documents_have_labels=True
    for document,proposal in zip(privacy_pending["documents"],privacy_pending["proposals"]):
        pages=render_pages(document["path"])
        regions=[]
        for number,page in enumerate(pages,1):
            page_regions=[r for r in proposal["regions"] if r["page"]==number]
            for message in acquisition_report(page,page_regions)["warnings"]:st.warning(message)
        for index,region in enumerate(proposal["regions"]):
            crop=crop_region(pages[region["page"]-1],region["bbox"])
            st.image(crop,caption=f"{document['name']} · etichetta {index+1}",use_container_width=True)
            decode_key=f"privacy_dm_{proposal['sha256']}_{index}"
            if decode_key not in st.session_state:
                st.session_state[decode_key]=bool([b for b in decode_barcodes(crop) if not b.get('error')])
            if not st.session_state[decode_key]:
                st.warning("DataMatrix non decodificato: acquisisci una nuova foto più ravvicinata, nitida e senza riflessi. Il testo sarà soltanto un controllo, non una corrispondenza GTIN verificata.")
            if st.checkbox("Questo ritaglio contiene solo l'etichetta del prodotto",value=False,key=f"privacy_crop_{proposal['sha256']}_{index}"):
                regions.append(region)
        if not regions:all_documents_have_labels=False
        selected[proposal["sha256"]]={**proposal,"regions":regions,"approved":True,"labels_only_confirmed":True}
    confirmed=st.checkbox("Ho controllato tutti i ritagli selezionati: nessun dato del paziente verrà inviato",value=False,key="scarico_privacy_confirmed")
    if st.button("Invia solo le etichette approvate al modello",disabled=not confirmed or not all_documents_have_labels,type="primary"):
        documents=privacy_pending["documents"]
        st.session_state.pop("scarico_privacy_pending",None)
        run_ai(documents[0]["path"],documents=documents,privacy_manifest=selected)
    if st.button("Annulla e acquisisci foto più ravvicinate"):
        st.session_state.pop("scarico_privacy_pending",None)
        st.rerun()
    st.stop()

meta = st.session_state.get("scarico_ai_meta", {}) or {}
source_rows = st.session_state.get("scarico_ai_rows", []) or []
if meta and st.session_state.get("scarico_source") == "AI":
    st.caption(f"Versione usata per questi risultati: {meta.get('pipeline_version') or 'precedente'}")
    if meta.get("pipeline_version") != PIPELINE_VERSION:
        st.warning("Questi risultati sono stati estratti con una versione OCR precedente. Rianalizza i documenti per applicare le correzioni ai ritagli e alla lettura.")
        if st.button("Rianalizza i documenti con la versione aggiornata", key="scarico_reanalyze_version"):
            documents = st.session_state.get("scarico_documents") or []
            if documents and all(Path(d.get("path", "")).is_file() for d in documents):
                run_ai(documents[0]["path"], documents=documents)
            else:
                st.error("Ricarica i documenti originali e premi Analizza tutti i file.")
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
is_physical_ai = st.session_state.get("scarico_source") == "AI"
if is_physical_ai:
    # Every detected observation remains reviewable, including other manufacturers.
    rows = [{**r, "jnj_verificato_manualmente": i in restored_indices,
             "escludi_riga": is_other_manufacturer(r.get("produttore")) and i not in restored_indices}
            for i, r in enumerate(source_rows)]
    excluded_rows = []
    st.subheader("Verifica delle etichette fisiche")
    for detection_warning in meta.get("detection_warnings", []) or []:
        st.warning(detection_warning)
    unconfirmed_regions = meta.get("unconfirmed_regions", []) or []
    if unconfirmed_regions:
        with st.expander("Zone proposte dall’AI da controllare sul documento originale"):
            st.caption("Queste zone non hanno un riscontro indipendente come etichette di prodotto e non aumentano la quantità. Se una zona contiene davvero un materiale, aggiungilo dal modulo qui sotto.")
            for region in unconfirmed_regions:
                if region.get("crop_data_url"):
                    st.image(region["crop_data_url"], caption=f"Pagina {region.get('page', '')}")
    with st.expander("Foto originali con le etichette individuate"):
        for page in meta.get("annotated_pages", []) or []:
            if page.get("page_data_url"):
                st.image(page["page_data_url"], caption=f"Pagina {page.get('page')}")
    cols = st.columns(3)
    cols[0].metric("Etichette individuate", len(source_rows))
    cols[1].metric("Articoli distinti (REF / lotto)", len({(r.get("codice"), r.get("lotto")) for r in source_rows if r.get("codice") and (r.get("lotto") or r.get("senza_lotto"))}))
    cols[2].metric("Quantità proposta da scaricare", "Da verificare" if any(r.get("cross_photo_candidates") and not r.get("physical_distinct_confirmed") and not r.get("duplicate_of") for r in rows) else sum(1 for r in rows if not r.get("escludi_riga")))
    catalog = None
    if source_rows:
        try:
            catalog = load_catalog_codes(sb())
            st.caption("Confronto REF con l’anagrafica scanner disponibile: può contenere solo parte del catalogo. I codici assenti vanno verificati, mai sostituiti automaticamente.")
        except Exception:
            st.caption("Anagrafica scanner non disponibile: confronto catalogo non eseguito.")
    assessed_rows = build_review({"items":source_rows}, catalog=catalog)["items"]
    for r in assessed_rows:
        with st.expander(f"{'⚠️ Da verificare' if r.get('assessment',{}).get('needs_review') else 'Da confermare'} · {r.get('label_id')} · {clean(r.get('codice'))} · {clean(r.get('lotto'))}"):
            left, right = st.columns([2, 3])
            if r.get("crop_data_url"):
                left.image(r["crop_data_url"], use_container_width=True)
            right.write({k:r.get(k) for k in ("codice", "lotto", "scadenza", "scadenza_originale", "descrizione", "produttore", "gtin")})
            if r.get("local_ref_evidence"):
                right.write({"REF letto inizialmente": r.get("ref_original"), "Controllo OCR locale": r["local_ref_evidence"]})
            if r.get("ocr_reads"):
                right.write({"Letture indipendenti": r["ocr_reads"]})
            assessment = r.get("assessment", {})
            right.dataframe(pd.DataFrame([{"Campo":name,"Esito":f["status"],"Metodo":f["method"],
                "Forza evidenza":f["score"]} for name,f in assessment.get("fields",{}).items()]),
                hide_index=True, use_container_width=True)
            right.caption("Forza dell’evidenza: indicatore tecnico, non probabilità di correttezza. Tutti i campi richiedono revisione.")
            for issue in assessment.get("issues",[]):
                right.warning(issue)
            right.caption(f"Pagina {r.get('page')} · posizione {r.get('bbox')} · rotazione {r.get('rotation')}°")
            if r.get("warning"):
                right.warning(r["warning"])
    try:
        preview_rows = aggregate_review(rows)
        if preview_rows:
            st.caption("Anteprima aggregata: ogni etichetta fisica vale un pezzo; stesso REF e lotto sommano la quantità.")
            st.dataframe(pd.DataFrame(preview_rows)[["code","lot","expiry","description","quantity"]], hide_index=True, use_container_width=True)
    except ValueError as exc:
        st.info(f"Anteprima aggregata disponibile dopo la verifica dei campi: {exc}")
    st.info("Confronta ogni ritaglio con la pagina originale. Se manca un'etichetta, aggiungila dal modulo qui sotto confrontandola con il documento originale. Verifica il conteggio completo prima della conferma.")
if is_physical_ai:
    st.subheader("Aggiungi o correggi un materiale")
    choices = list(range(len(source_rows))) + [-1]
    target = st.selectbox("Materiale da correggere", choices,
        format_func=lambda i: "➕ Nuova etichetta non riconosciuta" if i == -1 else f"{i+1} · {clean(source_rows[i].get('codice'))} · {clean(source_rows[i].get('lotto'))}",
        key="scarico_manual_target")
    selected = source_rows[target] if target >= 0 else {}
    documents = st.session_state.get("scarico_documents", []) or []
    with st.form(f"scarico_manual_material_{target}_{st.session_state.get('scarico_editor_revision', 0)}"):
        manual_code = st.text_input("REF / codice", value=clean(selected.get("codice")))
        manual_lot = st.text_input("Lotto stampato", value=clean(selected.get("lotto")))
        manual_gtin = st.text_input("GTIN (14 cifre, se leggibile)", value=clean(selected.get("gtin")))
        manual_expiry = st.text_input("Scadenza stampata (AAAA-MM-GG)", value=clean(selected.get("scadenza")))
        manual_description = st.text_input("Descrizione materiale", value=clean(selected.get("descrizione")))
        manual_lotless = st.checkbox("Materiale non sterile senza lotto", value=bool(selected.get("senza_lotto", False)))
        manual_verified = st.checkbox("Ho confrontato questi campi con l'etichetta originale", value=False)
        if target == -1 and documents:
            manual_document = st.selectbox("Documento contenente l'etichetta mancante", list(range(len(documents))), format_func=lambda i: documents[i]["name"])
            manual_page = st.number_input("Pagina dell'etichetta mancante", min_value=1, max_value=12, value=1, step=1)
            st.caption("La pagina originale sarà mostrata come prova. Una nuova riga rappresenta una sola etichetta fisica e un pezzo.")
        apply_manual = st.form_submit_button("Applica materiale alla lista", disabled=target == -1 and not documents)
    if apply_manual:
        if not manual_code.strip() or not manual_verified:
            st.error("Inserisci il REF e conferma il confronto con l'etichetta originale.")
        else:
            try:
                if manual_gtin.strip() and gs1_parse('(01)'+manual_gtin.strip()).get('error'):
                    raise ValueError("GTIN non valido: controlla le 14 cifre e il carattere di controllo.")
                updated = dict(selected)
                if target == -1:
                    from label_pipeline import render_pages, image_url
                    from uuid import uuid4
                    document = documents[manual_document]
                    pages = render_pages(document["path"])
                    if manual_page > len(pages):
                        raise ValueError("La pagina indicata non esiste nel documento.")
                    updated.update(label_id=f"manual:{uuid4().hex}", source_document=sha256(Path(document["path"]).read_bytes()).hexdigest(),
                        page=int(manual_page), bbox=[0,0,1000,1000], rotation=0,
                        crop_data_url=image_url(pages[int(manual_page)-1]), quantita=1,
                        warning="Etichetta aggiunta manualmente: prova sulla pagina originale.", manual_entry=True)
                updated.update(codice=manual_code.strip(), lotto=manual_lot.strip(), gtin=manual_gtin.strip() or None, scadenza=manual_expiry.strip(),
                    descrizione=manual_description.strip(), senza_lotto=manual_lotless, verificata=True,
                    manual_fields=["code","lot","expiry","description","gtin"])
                updated_rows = list(source_rows)
                if target == -1:
                    updated_rows.append(updated)
                else:
                    updated_rows[target] = updated
                st.session_state["scarico_ai_rows"] = updated_rows
                st.session_state["scarico_editor_revision"] = int(st.session_state.get("scarico_editor_revision", 0)) + 1
                st.rerun()
            except (ValueError, OSError) as exc:
                st.error(str(exc))
clients = client_options()
ai_clinic = clean(meta.get("clinic_name"))
if clients:
    default_idx = clinic_default_index(ai_clinic, clients)
    selected_client = st.selectbox("Struttura / cliente", clients, index=default_idx, format_func=lambda x: x["label"])
else:
    selected_client = {"codice_cliente": "", "descrizione": st.text_input("Struttura / cliente", value=ai_clinic)}


line = st.selectbox("Linea", ["TRAUMA", "PROTESICA", "CMF", "SPINE", "SPORTS", "ALTRO"], key="scarico_price_line")
is_malzoni = clean(selected_client.get("codice_cliente")) == "9010013"
if source_rows:
    st.caption(f"OCR: {len(source_rows)} righe riconosciute · {len(rows)} righe nella lista modificabile · {len(excluded_rows)} righe di altri produttori escluse.")
if excluded_rows:
    st.warning(f"{len(excluded_rows)} righe di altri produttori escluse dallo scarico, dal fatturato e dagli ordini P.M. Medical.")
    with st.expander("Materiale di altre aziende escluso"):
        st.dataframe(pd.DataFrame(excluded_rows), use_container_width=True, hide_index=True)
with st.form("scarico_ai_confirm"):
    if rows:
        st.divider()
        st.subheader("✅ Lista materiali riconosciuti")
        st.caption("Tocca una cella per correggere codice, lotto, scadenza o quantità. Per materiale non sterile senza lotto spunta Non sterile / senza lotto. Spunta Escludi riga per non inserirla nello scarico. Le modifiche vengono applicate alla conferma. Puoi anche usare il modulo Aggiungi o correggi un materiale sopra la lista.")
        df_rows = pd.DataFrame(rows)
        preferred = ["codice", "senza_lotto", "jnj_verificato_manualmente", "escludi_riga", "descrizione", "lotto", "gtin", "scadenza", "physical_distinct_confirmed", "duplicate_of", "quantita", "produttore", "confidence", "warning"]
        if "escludi_riga" not in df_rows:
            df_rows["escludi_riga"] = False
        df_rows["senza_lotto"] = df_rows.get("senza_lotto", pd.Series(False, index=df_rows.index)).fillna(False).astype(bool)
        df_rows["physical_distinct_confirmed"] = df_rows.get("physical_distinct_confirmed",pd.Series(False,index=df_rows.index)).fillna(False).astype(bool)
        df_rows["duplicate_of"] = df_rows.get("duplicate_of",pd.Series("",index=df_rows.index)).fillna("")
        for col in preferred:
            if col not in df_rows.columns:
                df_rows[col] = ""
        if is_malzoni:
            if "conto_deposito_struttura" not in df_rows.columns:
                df_rows["conto_deposito_struttura"] = False
            df_rows["conto_deposito_struttura"] = df_rows["conto_deposito_struttura"].fillna(False).astype(bool)
            preferred.insert(1, "conto_deposito_struttura")
            st.info("Malzoni: spunta il materiale della struttura Smart Track. Prezzi, fatturato e ordini restano inclusi; queste righe non scaricano la vostra giacenza.")
        if is_physical_ai:
            df_rows["verificata"] = df_rows.get("verificata", pd.Series(False, index=df_rows.index)).fillna(False).astype(bool)
            preferred = ["label_id", "verificata"] + preferred
        edited = st.data_editor(
            df_rows[preferred], num_rows="fixed" if is_physical_ai else "dynamic", use_container_width=True,
            disabled=["label_id", "confidence", "warning"] if is_physical_ai else [],
            height=min(1600, max(220, 35 * (len(df_rows) + 3))), row_height=35,
            column_config={
                "verificata": st.column_config.CheckboxColumn("Etichetta verificata", default=False, help="Confronta REF, lotto, scadenza e quantità con il singolo ritaglio e correggi prima di spuntare."),
                "jnj_verificato_manualmente": None,
                "escludi_riga": st.column_config.CheckboxColumn(
                    "Escludi riga", default=False,
                    help="La riga non verrà salvata e non genererà fatturato, ordini o movimenti di magazzino."),
                "codice": st.column_config.TextColumn("Codice Johnson/REF"),
                "lotto": st.column_config.TextColumn("Lotto"),
                "gtin": st.column_config.TextColumn("GTIN (14 cifre)"),
                "physical_distinct_confirmed": st.column_config.CheckboxColumn("Pezzo fisico distinto nelle altre foto",default=False),
                "duplicate_of": st.column_config.TextColumn("Stessa etichetta già vista: ID della prima riga"),
                "senza_lotto": st.column_config.CheckboxColumn("Non sterile / senza lotto", default=False,
                    help="Spunta solo materiale non sterile che non prevede lotto. La disponibilità viene cercata nelle giacenze senza lotto."),
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

    st.info("Lotti, scadenze o quantità non corrispondenti al magazzino non bloccano la registrazione: l’intervento viene salvato e le righe interessate vanno in Anomalie Prezzi e Giacenze, senza scalare giacenze non corrispondenti.")

    c1, c2 = st.columns(2)
    with c1:
        procedure_date = st.date_input("Data intervento", value=ai_date.date() if pd.notna(ai_date) else date.today(), min_value=date(1900, 1, 1), max_value=date(max(date.today().year + 10, ai_date.year if pd.notna(ai_date) else date.today().year), 12, 31), format="DD/MM/YYYY")
        clinical_record = st.text_input("Numero cartella clinica", value=ai_record)
        surgeon = st.text_input("Chirurgo", value=ai_surgeon)
    with c2:
        wh = st.selectbox("Scarica da giacenza", warehouses)
        mag = wh.split(" - ")[0]
        agent = st.selectbox("Agente", agents) if agents and agents != [""] else st.text_input("Agente")

    expected_label_count = st.number_input("Numero di etichette contate sul documento originale", min_value=0, step=1, value=0, key=f"physical_count_{st.session_state.get('scarico_editor_revision', 0)}") if is_physical_ai else 0
    count_verified = st.checkbox("Ho confrontato tutti i ritagli con il documento originale e verificato il conteggio fisico.", value=False, key=f"physical_verified_{st.session_state.get('scarico_editor_revision', 0)}") if is_physical_ai else True
    header_verified = st.checkbox("Ho verificato struttura, data e dati intervento sul documento originale.", value=False, key=f"physical_header_verified_{st.session_state.get('scarico_editor_revision', 0)}") if is_physical_ai else True
    verified = st.checkbox("Ho verificato codice Johnson/REF, lotto, scadenza e quantità di tutte le righe.")
    archive_enabled = str(secret("OCR_REVIEW_ARCHIVE_ENABLED", "false")).lower() in {"true","1","yes"}
    archive_review = st.form_submit_button("Conferma e archivia revisione OCR (senza scarico)", disabled=(not is_physical_ai or not archive_enabled or len(rows)==0))
    confirm = st.form_submit_button("📤 Crea intervento e scarica materiali", type="primary", use_container_width=True, disabled=(len(rows) == 0))

if confirm or archive_review:
    if any(d.get("status")=="failed" for d in meta.get("documents",[]) if isinstance(d,dict)):
        st.error("Uno o più documenti non sono stati analizzati: ripeti la lettura o acquisisci una nuova foto prima della conferma.")
        st.stop()
    if not verified:
        st.error("Conferma di aver verificato i materiali prima di creare l’intervento.")
        st.stop()
    final_rows = edited.to_dict("records") if rows else []
    if is_physical_ai:
        final_rows = merge_confirmed_fields(source_rows, final_rows)
        errors = review_errors(final_rows, [r.get("label_id") for r in source_rows], expected_label_count, count_verified)
        if errors:
            st.error("Conferma bloccata: " + "; ".join(errors))
            st.stop()
        if not header_verified:
            st.error("Conferma bloccata: verifica struttura, data e dati intervento sul documento originale.")
            st.stop()
    if is_physical_ai and archive_enabled:
        try:
            original_map = {r.get("label_id"):r for r in st.session_state.get("scarico_ai_original_rows", [])}
            if any(not r.get("manual_entry") and r.get("label_id") not in original_map for r in source_rows):
                raise ValueError("Rianalizza i documenti: manca la copia immutabile dell’estrazione originale per questa vecchia sessione.")
            extraction = {**meta, "items":[original_map.get(r.get("label_id"),r) for r in source_rows]}
            payload_key = sha256(json.dumps(without_images(final_rows), sort_keys=True, default=str).encode()).hexdigest()
            previous = st.session_state.get("scarico_audit_request") or {}
            if previous.get("payload_key")!=payload_key:
                previous = {"payload_key":payload_key,"id":str(uuid4())}
                st.session_state["scarico_audit_request"] = previous
            documents = [OriginalDocument(d.get("name") or Path(d["path"]).name, Path(d["path"]).read_bytes())
                         for d in st.session_state.get("scarico_documents", [])]
            saved = SupabaseReviewRepository(sb()).save_confirmed(
                request_id=previous["id"],actor=user(),extraction=extraction,confirmed=final_rows,
                documents=documents,physical_count=int(expected_label_count),
                count_verified=bool(count_verified),explicitly_confirmed=True)
            if archive_review:
                st.success(f"Revisione {saved['id']} archiviata con foto originali. Nessuno scarico di magazzino eseguito.")
                st.stop()
        except Exception as exc:
            st.error(f"Archivio OCR non completato: {exc}. I campi corretti restano nella sessione; nessuno scarico eseguito.")
            st.stop()
    valid_rows = []
    invalid_lots = []
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
        no_lot = bool(r.get("senza_lotto", False))
        if code and qty > 0:
            if not lot and not no_lot:
                invalid_lots.append(code)
            elif lot and no_lot:
                invalid_lots.append(f"{code}: togli la spunta senza lotto oppure svuota il lotto")
            else:
                valid_rows.append((r, code, lot, qty))

    if invalid_lots:
        st.error("Verifica il lotto oppure spunta Non sterile / senza lotto: " + ", ".join(invalid_lots))
        st.stop()

    if not valid_rows:
        st.error("Nessuna riga valida: servono codice e quantità > 0; il lotto è richiesto salvo materiale confermato non sterile senza lotto.")
        st.stop()

    if is_physical_ai:
        checked_rows = [r for r, _, _, _ in valid_rows
                        if not (is_malzoni and bool(r.get("conto_deposito_struttura", False)))]
        try:
            stock, offset = [], 0
            while True:
                batch = (sb().table("giacenze").select("codice,lotto,scadenza,quantita")
                    .eq("codice_magazzino", mag).eq("origine", "CONTO DEPOSITO")
                    .order("id").range(offset, offset + 499).execute().data or [])
                stock.extend(batch)
                if len(batch) < 500:
                    break
                offset += 500
            identity_errors = inventory_errors(checked_rows, stock)
        except Exception:
            identity_errors = ["Magazzino non verificabile: riprovare prima di confermare"]
        if identity_errors:
            st.warning("Intervento registrabile: le discrepanze di magazzino saranno salvate nelle anomalie. " + "; ".join(identity_errors))

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
        st.warning("Quantità insufficienti: l’intervento sarà registrato e le righe saranno segnalate nelle anomalie di giacenza.")
    else:
        st.session_state.pop("scarico_stock_errors", None)

    if is_physical_ai:
        grouped = aggregate_labels([r for r, _, _, _ in valid_rows])
        valid_rows = [(r, clean(r.get("codice")), clean(r.get("lotto")), float(r["quantita"])) for r in grouped]
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
            "label_ids": r.get("label_ids", []),
            "verificata": bool(r.get("verificata", False)),
            "codice": code,
            "is_sterile": bool(r.get("is_sterile", False)) or code.upper().endswith('S'),
            "descrizione": clean(r.get("descrizione")),
            "lotto": lot,
            "senza_lotto": bool(r.get("senza_lotto", False)),
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

    if is_physical_ai:
        header["physical_label_count"] = int(expected_label_count)
        header["count_verified"] = bool(count_verified)
        header["included_label_ids"] = [i for r in rpc_rows for i in r["label_ids"]]
        originals = {r.get("label_id"): r for r in st.session_state.get("scarico_ai_original_rows", source_rows)}
        header["label_manifest"] = [{
            "label_id": r.get("label_id"),
            "source_document": originals.get(r.get("label_id"), {}).get("source_document"),
            "page": originals.get(r.get("label_id"), {}).get("page"),
            "bbox": originals.get(r.get("label_id"), {}).get("bbox"),
            "rotation": originals.get(r.get("label_id"), {}).get("rotation"),
            "codice": clean(r.get("codice")), "lotto": clean(r.get("lotto")),
            "scadenza": clean(r.get("scadenza")),
            "scadenza_originale": originals.get(r.get("label_id"), {}).get("scadenza_originale"),
            "verificata": bool(r.get("verificata")),
            "evidenze_estratte": without_images(originals.get(r.get("label_id"), {})),
            "dati_confermati": without_images(r),
            "esclusa": bool(r.get("escludi_riga")) or is_other_manufacturer(r.get("produttore")),
        } for r in final_rows]
    try:
        result = sb().rpc("crea_intervento_scarico_ai_verificato" if is_physical_ai else "crea_intervento_scarico_ai_flessibile", {
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
        anomaly_count = int(result.get("anomalie", 0) or 0)
        if anomaly_count:
            st.warning(f"{anomaly_count} righe registrate nelle Anomalie Prezzi e Giacenze: quantità, lotto o scadenza non corrispondenti. La giacenza di queste righe non è stata scalata; verifica e riconcilia le anomalie.")
        if not doc_ok:
            st.warning("Intervento e magazzino sono stati salvati correttamente, ma il documento originale non è stato archiviato. Puoi ricaricarlo dall'Archivio impianti.")

        for k in ["scarico_pending_files", "scarico_documents", "scarico_ai_rows", "scarico_ai_original_rows", "scarico_audit_request", "scarico_ai_meta", "scarico_file_path", "scarico_file_name", "scarico_file_type", "scarico_source", "scarico_missing_prices", "scarico_stock_errors", "scarico_verified"]:
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



