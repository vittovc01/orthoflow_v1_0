import os
import json
import base64
import calendar
import re
from pathlib import Path
from typing import List, Dict, Any
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

def _secret(name: str, default: str = "") -> str:
    try:
        import streamlit as st
        if name in st.secrets:
            value=st.secrets.get(name)
            if value is not None: return str(value)
    except Exception: pass
    return str(os.getenv(name,default) or default)

def _flag(name: str, default: str="false") -> bool:
    return _secret(name,default).strip().lower() in {"1","true","yes","y","on"}

def ai_status():
    missing=[]
    if not _secret("OPENAI_API_KEY"): missing.append("OPENAI_API_KEY")
    if not _flag("ENABLE_AI_OCR","false"): missing.append("ENABLE_AI_OCR=true")
    return {"enabled":not missing,"missing":missing,"model":_secret("OPENAI_VISION_MODEL","gpt-5-mini")}

def ai_enabled(): return bool(ai_status()["enabled"])

def _responses_json_schema_format(schema_obj):
    js=schema_obj.get("json_schema",{})
    return {"type":"json_schema","name":js.get("name","orthoflow_extraction"),"schema":js.get("schema",{}),"strict":bool(js.get("strict",True))}

SUPPORTED_IMAGE_EXT={".jpg",".jpeg",".png",".webp"}
SUPPORTED_DOCUMENT_EXT=SUPPORTED_IMAGE_EXT|{".pdf"}
ITEM_PROPERTIES={
    "code":{"type":["string","null"]},"lot":{"type":["string","null"]},"expiry":{"type":["string","null"]},
    "description":{"type":["string","null"]},"quantity":{"type":"number"},"manufacturer":{"type":["string","null"]},
    "is_jnj_depuy_synthes":{"type":"boolean"},"is_sterile":{"type":"boolean"},"source_text":{"type":["string","null"]},
    "confidence":{"type":"number"},"warning":{"type":["string","null"]}}
ITEM_REQUIRED=list(ITEM_PROPERTIES.keys())

def _items_schema(): return {"type":"array","items":{"type":"object","properties":ITEM_PROPERTIES,"required":ITEM_REQUIRED,"additionalProperties":False}}
SCARICO_SALA_SCHEMA={"type":"json_schema","json_schema":{"name":"scarico_sala_extraction","strict":True,"schema":{"type":"object","properties":{"document_type":{"type":"string"},"clinic_name":{"type":["string","null"]},"clinical_record":{"type":["string","null"]},"procedure_date":{"type":["string","null"]},"surgeon":{"type":["string","null"]},"confidence":{"type":"number"},"items":_items_schema(),"back_orders":_items_schema()},"required":["document_type","clinic_name","clinical_record","procedure_date","surgeon","confidence","items","back_orders"],"additionalProperties":False}}}
DDT_SCHEMA={"type":"json_schema","json_schema":{"name":"ddt_extraction","strict":True,"schema":{"type":"object","properties":{"document_type":{"type":"string"},"ddt_number":{"type":["string","null"]},"ddt_date":{"type":["string","null"]},"customer":{"type":["string","null"]},"destination":{"type":["string","null"]},"transport_reason":{"type":["string","null"]},"is_loan_or_conto_visione":{"type":"boolean"},"confidence":{"type":"number"},"items":_items_schema()},"required":["document_type","ddt_number","ddt_date","customer","destination","transport_reason","is_loan_or_conto_visione","confidence","items"],"additionalProperties":False}}}

def image_to_data_url(path):
    p=Path(path); mime={".png":"image/png",".webp":"image/webp",".jpg":"image/jpeg",".jpeg":"image/jpeg"}.get(p.suffix.lower(),"image/jpeg")
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode('utf-8')}"

def _instructions(mode):
    if mode=="ddt":
        return """Sei il modulo documentale di OrthoFlow Control Tower per DDT Johnson & Johnson / DePuy Synthes. Analizza TUTTO il documento e TUTTE le pagine. Estrai numero e data DDT, cliente, destinazione, causale e ogni riga EFFETTIVAMENTE SPEDITA con REF/codice Johnson, lotto, scadenza, descrizione e quantità spedita. Il REF deve essere identico allo stampato: punti, zeri e S finale sono significativi. 413.050S è diverso da 413.050. IMPORTANTE: separa le righe NON SPEDITE/back order/prodotto non spedito in back_orders; non inserirle mai in items. Per ogni back order estrai REF/codice, descrizione e quantità ordinata/non spedita quando leggibile; lotto e scadenza possono essere null. Per le righe spedite leggi SEMPRE la scadenza stampata sul DDT quando presente, inclusi formati MM/YY, MM/YYYY, DD/MM/YY e DD/MM/YYYY. Non inventare valori; se incerto usa null/warning."""
    return """Sei il modulo documentale di OrthoFlow Control Tower per scarichi di sala ortopedica. Analizza tutto il documento/immagine. Estrai struttura, cartella clinica, data, chirurgo e per ogni etichetta/materiale REF esatto, lotto, scadenza, descrizione, quantità e produttore. Mantieni punti, zeri e S finale. Per le scadenze restituisci preferibilmente YYYY-MM-DD; se sull'etichetta compare solo mese/anno, conserva mese e anno senza inventare un giorno. Non inventare valori; usa warning se incerto."""

def _parse_response(response):
    text=getattr(response,"output_text",None)
    if not text:
        try: text=response.output[0].content[0].text
        except Exception as exc: raise RuntimeError("La risposta OCR AI non contiene output utilizzabile.") from exc
    return json.loads(text)

def analyze_document(path: str, mode: str="scarico_sala") -> Dict[str,Any]:
    status=ai_status()
    if not status["enabled"]: raise RuntimeError("AI OCR non abilitato. Configura OPENAI_API_KEY e ENABLE_AI_OCR=true nei Secrets.")
    p=Path(path)
    if not p.exists(): raise FileNotFoundError(f"Documento non trovato: {path}")
    if p.suffix.lower() not in SUPPORTED_DOCUMENT_EXT: raise ValueError("Formato non supportato. Usa PDF, JPG, JPEG, PNG o WEBP.")
    client=OpenAI(api_key=_secret("OPENAI_API_KEY")); schema=DDT_SCHEMA if mode=="ddt" else SCARICO_SALA_SCHEMA
    if p.suffix.lower()==".pdf":
        pdf_b64=base64.b64encode(p.read_bytes()).decode("utf-8")
        content=[
            {"type":"input_text","text":"Analizza tutte le pagine del PDF. Restituisci esclusivamente i dati conformi allo schema strutturato."},
            {"type":"input_file","filename":p.name,"file_data":f"data:application/pdf;base64,{pdf_b64}","detail":"high"}
        ]
    else:
        content=[{"type":"input_text","text":"Analizza il documento. Restituisci esclusivamente i dati conformi allo schema strutturato."},{"type":"input_image","image_url":image_to_data_url(path),"detail":"high"}]
    response=client.responses.create(model=status["model"],store=False,input=[{"role":"system","content":_instructions(mode)},{"role":"user","content":content}],text={"format":_responses_json_schema_format(schema)})
    return _parse_response(response)

def analyze_image(path: str, mode: str="scarico_sala") -> Dict[str,Any]:
    return analyze_document(path,mode)

def _normalize_expiry(value):
    """Return a PostgreSQL DATE-safe ISO value. Month-only expiries use month-end."""
    s=str(value or "").strip()
    if not s: return ""
    # Already complete ISO date.
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}",s): return s
    # AI commonly returns YYYY-MM when the label only contains month/year.
    m=re.fullmatch(r"(\d{4})[-/](\d{1,2})",s)
    if m:
        y,mo=int(m.group(1)),int(m.group(2))
        if 1 <= mo <= 12:
            return f"{y:04d}-{mo:02d}-{calendar.monthrange(y,mo)[1]:02d}"
    # Also accept MM/YYYY or MM-YYYY.
    m=re.fullmatch(r"(\d{1,2})[-/](\d{4})",s)
    if m:
        mo,y=int(m.group(1)),int(m.group(2))
        if 1 <= mo <= 12:
            return f"{y:04d}-{mo:02d}-{calendar.monthrange(y,mo)[1]:02d}"
    # Common full Italian/European date.
    m=re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})",s)
    if m:
        d,mo,y=map(int,m.groups())
        try:
            import datetime
            return datetime.date(y,mo,d).isoformat()
        except ValueError: return ""
    return ""

def normalize_ai_items(result):
    out=[]
    for it in result.get("items",[]):
        code=(it.get("code") or "").strip(); manufacturer=(it.get("manufacturer") or "").strip()
        raw_expiry=it.get("expiry") or ""
        expiry=_normalize_expiry(raw_expiry)
        warning=it.get("warning") or ""
        if raw_expiry and not expiry:
            warning=(warning+" · " if warning else "")+f"Scadenza da verificare: {raw_expiry}"
        out.append({"codice":code,"descrizione":it.get("description") or "","lotto":(it.get("lot") or "").strip(),"scadenza":expiry,"quantita":it.get("quantity") or 1,"produttore":manufacturer,"is_jnj":bool(it.get("is_jnj_depuy_synthes",False)),"is_sterile":bool(it.get("is_sterile",code.upper().endswith("S"))),"confidence":float(it.get("confidence") or 0),"warning":warning,"source_text":it.get("source_text") or ""})
    return out