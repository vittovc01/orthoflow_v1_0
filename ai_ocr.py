import os
import json
import base64
from pathlib import Path
from typing import List, Dict, Any

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


def _secret(name: str, default: str = "") -> str:
    """Legge prima Streamlit Secrets, poi variabili ambiente/.env."""
    try:
        import streamlit as st
        if name in st.secrets:
            value = st.secrets.get(name)
            if value is not None:
                return str(value)
    except Exception:
        pass
    return str(os.getenv(name, default) or default)


def _flag(name: str, default: str = "false") -> bool:
    return _secret(name, default).strip().lower() in {"1", "true", "yes", "y", "on"}


def ai_status() -> Dict[str, Any]:
    missing = []
    if not _secret("OPENAI_API_KEY"):
        missing.append("OPENAI_API_KEY")
    if not _flag("ENABLE_AI_OCR", "false"):
        missing.append("ENABLE_AI_OCR=true")
    return {
        "enabled": not missing,
        "missing": missing,
        "model": _secret("OPENAI_VISION_MODEL", "gpt-5-mini"),
    }


def ai_enabled() -> bool:
    return bool(ai_status()["enabled"])


def _responses_json_schema_format(schema_obj: dict) -> dict:
    js = schema_obj.get("json_schema", {})
    return {
        "type": "json_schema",
        "name": js.get("name", "orthoflow_extraction"),
        "schema": js.get("schema", {}),
        "strict": bool(js.get("strict", True)),
    }


SUPPORTED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}

ITEM_PROPERTIES = {
    "code": {"type": ["string", "null"]},
    "lot": {"type": ["string", "null"]},
    "expiry": {"type": ["string", "null"]},
    "description": {"type": ["string", "null"]},
    "quantity": {"type": "number"},
    "manufacturer": {"type": ["string", "null"]},
    "is_jnj_depuy_synthes": {"type": "boolean"},
    "is_sterile": {"type": "boolean"},
    "source_text": {"type": ["string", "null"]},
    "confidence": {"type": "number"},
    "warning": {"type": ["string", "null"]},
}
ITEM_REQUIRED = list(ITEM_PROPERTIES.keys())

SCARICO_SALA_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "scarico_sala_extraction",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "document_type": {"type": "string"},
                "clinic_name": {"type": ["string", "null"]},
                "clinical_record": {"type": ["string", "null"]},
                "procedure_date": {"type": ["string", "null"]},
                "surgeon": {"type": ["string", "null"]},
                "confidence": {"type": "number"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": ITEM_PROPERTIES,
                        "required": ITEM_REQUIRED,
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "document_type", "clinic_name", "clinical_record", "procedure_date",
                "surgeon", "confidence", "items"
            ],
            "additionalProperties": False,
        },
    },
}

DDT_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "ddt_extraction",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "document_type": {"type": "string"},
                "ddt_number": {"type": ["string", "null"]},
                "ddt_date": {"type": ["string", "null"]},
                "customer": {"type": ["string", "null"]},
                "destination": {"type": ["string", "null"]},
                "transport_reason": {"type": ["string", "null"]},
                "is_loan_or_conto_visione": {"type": "boolean"},
                "confidence": {"type": "number"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": ITEM_PROPERTIES,
                        "required": ITEM_REQUIRED,
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "document_type", "ddt_number", "ddt_date", "customer", "destination",
                "transport_reason", "is_loan_or_conto_visione", "confidence", "items"
            ],
            "additionalProperties": False,
        },
    },
}


def image_to_data_url(path: str) -> str:
    p = Path(path)
    suffix = p.suffix.lower()
    mime = {
        ".png": "image/png",
        ".webp": "image/webp",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }.get(suffix, "image/jpeg")
    data = base64.b64encode(p.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{data}"


def _instructions(mode: str) -> str:
    if mode == "ddt":
        return """
Sei il modulo di visione documentale di OrthoFlow Control Tower, specializzato in DDT e documenti logistici Johnson & Johnson / DePuy Synthes.
Analizza TUTTA l'immagine, inclusi intestazione, tabelle, etichette e righe in basso.
Estrai numero/data DDT, cliente, destinazione, causale e se si tratta di CONTO VISIONE, CONTO DEPOSITO, LOAN, IN o OUT.
Per ogni materiale estrai REF/codice, LOT/lotto, scadenza, descrizione, quantità e produttore.
Il codice REF deve essere IDENTICO a quello stampato: punti, zeri e S finale sono significativi. 413.050S è diverso da 413.050.
Non dedurre o inventare valori. Se un campo è incerto usa null e compila warning. Una confezione/etichetta visibile normalmente vale quantità 1 salvo indicazione esplicita diversa.
"""
    return """
Sei il modulo di visione documentale di OrthoFlow Control Tower, specializzato negli scarichi di sala operatoria ortopedica.
Analizza TUTTA l'immagine ad alta attenzione: modulo, foglio di scarico, etichette adesive e confezioni visibili.
Estrai, quando realmente leggibili, struttura/clinica, numero cartella clinica, data intervento e chirurgo.
Per OGNI etichetta o confezione materiale estrai REF/codice, LOT/lotto, scadenza, descrizione, quantità e produttore.
REGOLE CRITICHE:
- Il REF va restituito ESATTAMENTE come stampato. Mantieni punti, zeri iniziali e soprattutto la S finale.
- 413.050S e 413.050 sono due codici diversi. Non aggiungere e non togliere mai la S.
- Considera Johnson & Johnson / J&J / DePuy Synthes / Synthes come J&J. Non classificare altri produttori come J&J.
- Non ricostruire un lotto o una scadenza se non sono leggibili.
- Una singola etichetta normalmente corrisponde a quantità 1; somma solo se la quantità è chiaramente esplicita.
- Se una parte è poco leggibile, abbassa confidence e scrivi una warning invece di inventare.
- source_text deve riportare una breve trascrizione della zona da cui hai ricavato la riga, utile per il controllo umano.
L'output serve come precompilazione: l'operatore verificherà sempre i dati prima dello scarico definitivo.
"""


def analyze_image(path: str, mode: str = "scarico_sala") -> Dict[str, Any]:
    status = ai_status()
    if not status["enabled"]:
        raise RuntimeError(
            "AI OCR non abilitato. Configura nei Secrets: OPENAI_API_KEY e ENABLE_AI_OCR=true."
        )

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Immagine non trovata: {path}")
    if p.suffix.lower() not in SUPPORTED_IMAGE_EXT:
        raise ValueError("Formato immagine non supportato per OCR AI.")

    model = status["model"]
    client = OpenAI(api_key=_secret("OPENAI_API_KEY"))
    schema = DDT_SCHEMA if mode == "ddt" else SCARICO_SALA_SCHEMA

    response = client.responses.create(
        model=model,
        store=False,
        input=[
            {
                "role": "system",
                "content": _instructions(mode),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "Analizza il documento. Restituisci esclusivamente i dati conformi allo schema strutturato.",
                    },
                    {
                        "type": "input_image",
                        "image_url": image_to_data_url(path),
                        "detail": "high",
                    },
                ],
            },
        ],
        text={"format": _responses_json_schema_format(schema)},
    )

    text = getattr(response, "output_text", None)
    if not text:
        try:
            text = response.output[0].content[0].text
        except Exception as exc:
            raise RuntimeError("La risposta OCR AI non contiene output utilizzabile.") from exc
    return json.loads(text)


def normalize_ai_items(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for it in result.get("items", []):
        code = (it.get("code") or "").strip()
        lot = (it.get("lot") or "").strip()
        manufacturer = (it.get("manufacturer") or "").strip()
        out.append({
            "codice": code,
            "descrizione": it.get("description") or "",
            "lotto": lot,
            "scadenza": it.get("expiry") or "",
            "quantita": it.get("quantity") or 1,
            "produttore": manufacturer,
            "is_jnj": bool(it.get("is_jnj_depuy_synthes", False)),
            "is_sterile": bool(it.get("is_sterile", str(code).upper().endswith("S"))),
            "confidence": float(it.get("confidence") or 0),
            "warning": it.get("warning") or "",
            "source_text": it.get("source_text") or "",
        })
    return out
