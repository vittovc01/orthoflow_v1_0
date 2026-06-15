
import os
import json
import base64
from pathlib import Path
from typing import List, Dict, Any
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

SUPPORTED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}

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
                        "properties": {
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
                            "warning": {"type": ["string", "null"]}
                        },
                        "required": [
                            "code", "lot", "expiry", "description", "quantity",
                            "manufacturer", "is_jnj_depuy_synthes", "is_sterile",
                            "source_text", "confidence", "warning"
                        ],
                        "additionalProperties": False
                    }
                }
            },
            "required": [
                "document_type", "clinic_name", "clinical_record", "procedure_date",
                "surgeon", "confidence", "items"
            ],
            "additionalProperties": False
        }
    }
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
                        "properties": {
                            "code": {"type": ["string", "null"]},
                            "lot": {"type": ["string", "null"]},
                            "expiry": {"type": ["string", "null"]},
                            "description": {"type": ["string", "null"]},
                            "quantity": {"type": "number"},
                            "manufacturer": {"type": ["string", "null"]},
                            "is_sterile": {"type": "boolean"},
                            "source_text": {"type": ["string", "null"]},
                            "confidence": {"type": "number"},
                            "warning": {"type": ["string", "null"]}
                        },
                        "required": [
                            "code", "lot", "expiry", "description", "quantity",
                            "manufacturer", "is_sterile", "source_text", "confidence", "warning"
                        ],
                        "additionalProperties": False
                    }
                }
            },
            "required": [
                "document_type", "ddt_number", "ddt_date", "customer", "destination",
                "transport_reason", "is_loan_or_conto_visione", "confidence", "items"
            ],
            "additionalProperties": False
        }
    }
}

def ai_enabled() -> bool:
    return os.getenv("ENABLE_AI_OCR", "false").lower() == "true" and bool(os.getenv("OPENAI_API_KEY"))

def image_to_data_url(path: str) -> str:
    p = Path(path)
    mime = "image/jpeg"
    if p.suffix.lower() == ".png":
        mime = "image/png"
    elif p.suffix.lower() == ".webp":
        mime = "image/webp"
    data = base64.b64encode(p.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{data}"

def analyze_image(path: str, mode: str = "scarico_sala") -> Dict[str, Any]:
    if not ai_enabled():
        raise RuntimeError("AI OCR non abilitato. Imposta OPENAI_API_KEY e ENABLE_AI_OCR=true.")

    model = os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini")
    client = OpenAI()

    if mode == "ddt":
        schema = DDT_SCHEMA
        instructions = """
Sei un motore OCR specializzato su DDT Johnson & Johnson / DePuy Synthes.
Estrai testata documento e righe materiali. Identifica se il DDT è 'CONTO VISIONE', 'CONTO DEPOSITO', 'LOAN', 'IN/OUT'.
Per ogni etichetta e per ogni riga estrai codice prodotto, lotto, scadenza, descrizione, quantità. Non fermarti alle prime righe: analizza tutta l'immagine.
Non inventare dati. Se ci sono più etichette, restituisci una riga per ogni etichetta visibile. Se un campo non è leggibile usa null e warning.
"""
    else:
        schema = SCARICO_SALA_SCHEMA
        instructions = """
Sei un motore OCR specializzato su scarichi sala operatoria ortopedici.
Leggi anche il nome della clinica/struttura in alto nel modulo. Leggi etichette DePuy Synthes / Johnson & Johnson / Synthes e identifica REF/codice, LOT/lotto, scadenza, descrizione, produttore.
Accetta come J&J solo Johnson & Johnson, J&J, DePuy Synthes, Synthes.
Se trovi Smith & Nephew, Stryker, Zimmer Biomet o altri produttori, is_jnj_depuy_synthes=false.
Non inventare dati. Se ci sono più etichette, restituisci una riga per ogni etichetta visibile. Se un campo non è leggibile usa null e warning.
La quantità normalmente è 1 per etichetta, ma se sono presenti più etichette uguali puoi mantenere righe separate o sommare solo se chiarissimo.
"""

    data_url = image_to_data_url(path)

    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "system",
                "content": instructions
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Analizza questa immagine e restituisci esclusivamente JSON conforme allo schema."},
                    {"type": "input_image", "image_url": data_url}
                ]
            }
        ],
        response_format=schema,
    )

    text = response.output_text
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
            "confidence": it.get("confidence") or 0,
            "warning": it.get("warning") or "",
            "source_text": it.get("source_text") or ""
        })
    return out
