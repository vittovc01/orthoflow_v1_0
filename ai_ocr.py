import os
import json
import base64
import re
from pathlib import Path
from typing import List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

SUPPORTED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}

def openai_enabled() -> bool:
    return os.getenv("ENABLE_AI_OCR", "false").lower() == "true" and bool(os.getenv("OPENAI_API_KEY"))

def free_ocr_enabled() -> bool:
    # Attivo di default, così non serve pagare API.
    return os.getenv("ENABLE_FREE_OCR", "true").lower() == "true"

def ai_enabled() -> bool:
    # L'app usa questa funzione per abilitare il pulsante OCR.
    return openai_enabled() or free_ocr_enabled()

def image_to_data_url(path: str) -> str:
    p = Path(path)
    mime = "image/jpeg"
    if p.suffix.lower() == ".png":
        mime = "image/png"
    elif p.suffix.lower() == ".webp":
        mime = "image/webp"
    data = base64.b64encode(p.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{data}"

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
                "items": {"type": "array", "items": {"type": "object"}}
            },
            "required": ["document_type", "clinic_name", "clinical_record", "procedure_date", "surgeon", "confidence", "items"],
            "additionalProperties": True
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
                "items": {"type": "array", "items": {"type": "object"}}
            },
            "required": ["document_type", "ddt_number", "ddt_date", "customer", "destination", "transport_reason", "is_loan_or_conto_visione", "confidence", "items"],
            "additionalProperties": True
        }
    }
}

def _analyze_openai(path: str, mode: str = "scarico_sala") -> Dict[str, Any]:
    from openai import OpenAI

    model = os.getenv("OPENAI_VISION_MODEL", "gpt-4.1-mini")
    client = OpenAI()

    if mode == "ddt":
        schema = DDT_SCHEMA
        instructions = """
Sei un motore OCR specializzato su DDT Johnson & Johnson / DePuy Synthes.
Estrai testata documento e righe materiali. Identifica se il DDT è CONTO VISIONE, CONTO DEPOSITO, LOAN, IN/OUT.
Per ogni riga estrai codice prodotto, lotto, scadenza, descrizione, quantità. Non inventare.
"""
    else:
        schema = SCARICO_SALA_SCHEMA
        instructions = """
Sei un motore OCR specializzato su scarichi sala operatoria ortopedici.
Leggi nome struttura/clinica, cartella clinica, chirurgo, data, codici, lotti, scadenze e produttore.
Accetta come J&J solo Johnson & Johnson, J&J, DePuy Synthes, Synthes.
Se trovi Smith & Nephew, Stryker, Zimmer Biomet o altri produttori, is_jnj_depuy_synthes=false.
Non inventare.
"""

    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": instructions},
            {"role": "user", "content": [
                {"type": "input_text", "text": "Analizza questa immagine e restituisci esclusivamente JSON."},
                {"type": "input_image", "image_url": image_to_data_url(path)}
            ]}
        ],
        response_format=schema,
    )
    return json.loads(response.output_text)

def _ocr_image_text(path: str) -> str:
    from PIL import Image, ImageOps, ImageEnhance
    import pytesseract

    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    img = img.convert("L")
    img = ImageEnhance.Contrast(img).enhance(1.8)
    img = ImageEnhance.Sharpness(img).enhance(1.4)

    try:
        return pytesseract.image_to_string(img, lang="ita+eng")
    except Exception:
        return pytesseract.image_to_string(img)

def _ocr_pdf_text(path: str) -> str:
    try:
        from pdf2image import convert_from_path
        import pytesseract
        from PIL import ImageOps, ImageEnhance

        pages = convert_from_path(path, dpi=220, first_page=1, last_page=3)
        texts = []
        for img in pages:
            img = ImageOps.exif_transpose(img)
            img = img.convert("L")
            img = ImageEnhance.Contrast(img).enhance(1.8)
            img = ImageEnhance.Sharpness(img).enhance(1.4)
            try:
                texts.append(pytesseract.image_to_string(img, lang="ita+eng"))
            except Exception:
                texts.append(pytesseract.image_to_string(img))
        return "\n".join(texts)
    except Exception:
        return ""

def _guess_clinic(text: str):
    lines = [re.sub(r"\s+", " ", x).strip() for x in text.splitlines() if x.strip()]
    keywords = ["OSPED", "CLINIC", "CASA DI CURA", "VILLA", "A.O", "AOU", "AORN", "AZIENDA", "PRESIDIO", "POLICLINICO", "SAN ", "S.", "SANTA", "SANTO"]
    for line in lines[:30]:
        up = line.upper()
        if any(k in up for k in keywords) and len(line) >= 5:
            return line
    return lines[0] if lines else None

def _extract_codes(text: str):
    patterns = [
        r"\b\d{2}\.\d{3}\.\d{3,4}S?\b",
        r"\b\d{3}\.\d{3,4}S?\b",
        r"\b\d{2}\.\d{4}\.\d{3,4}S?\b",
    ]
    found = []
    up = text.upper()
    for pat in patterns:
        for m in re.findall(pat, up):
            if m not in found:
                found.append(m)
    return found

def _extract_lots(text: str):
    lots = []
    up = text.upper()
    patterns = [
        r"(?:LOT|LOTTO|BATCH|L\.?)\s*[:\-]?\s*([A-Z0-9]{4,20})",
        r"\b([A-Z]{1,3}\d{5,12})\b",
    ]
    for pat in patterns:
        for m in re.findall(pat, up):
            if m not in lots:
                lots.append(m)
    return lots

def _extract_expiries(text: str):
    dates = []
    up = text.upper()
    patterns = [
        r"\b(20\d{2}[-/\.]\d{1,2}[-/\.]\d{1,2})\b",
        r"\b(\d{1,2}[-/\.]\d{1,2}[-/\.]20\d{2})\b",
        r"(?:EXP|SCAD|SCADENZA)\s*[:\-]?\s*(\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4}|20\d{2}[-/\.]\d{1,2}[-/\.]\d{1,2})",
    ]
    for pat in patterns:
        for m in re.findall(pat, up):
            if m not in dates:
                dates.append(m)
    return dates

def _free_ocr_result(path: str, mode: str):
    p = Path(path)
    text = _ocr_pdf_text(path) if p.suffix.lower() == ".pdf" else _ocr_image_text(path)
    up = text.upper()

    clinic = _guess_clinic(text)
    codes = _extract_codes(text)
    lots = _extract_lots(text)
    expiries = _extract_expiries(text)
    is_jnj = any(w in up for w in ["DEPUY", "SYNTHES", "JOHNSON", "J&J"])

    items = []
    for i, code in enumerate(codes):
        items.append({
            "code": code,
            "lot": lots[i] if i < len(lots) else None,
            "expiry": expiries[i] if i < len(expiries) else None,
            "description": "",
            "quantity": 1,
            "manufacturer": "DePuy Synthes" if is_jnj else None,
            "is_jnj_depuy_synthes": is_jnj,
            "is_sterile": str(code).upper().endswith("S"),
            "source_text": text[:1000],
            "confidence": 0.55,
            "warning": "OCR gratuito: controllare manualmente codice, lotto e scadenza."
        })

    if mode == "ddt":
        return {
            "document_type": "ddt_free_ocr",
            "ddt_number": None,
            "ddt_date": None,
            "customer": clinic,
            "destination": clinic,
            "transport_reason": "LOAN/CONTO VISIONE" if any(w in up for w in ["LOAN", "CONTO VISIONE", "VISIONE"]) else None,
            "is_loan_or_conto_visione": any(w in up for w in ["LOAN", "CONTO VISIONE", "VISIONE"]),
            "confidence": 0.55,
            "items": items,
            "raw_text": text
        }

    return {
        "document_type": "scarico_sala_free_ocr",
        "clinic_name": clinic,
        "clinical_record": None,
        "procedure_date": None,
        "surgeon": None,
        "confidence": 0.55,
        "items": items,
        "raw_text": text
    }

def analyze_image(path: str, mode: str = "scarico_sala") -> Dict[str, Any]:
    if openai_enabled():
        return _analyze_openai(path, mode)
    if free_ocr_enabled():
        return _free_ocr_result(path, mode)
    raise RuntimeError("OCR non abilitato. Attiva ENABLE_FREE_OCR=true oppure configura OPENAI_API_KEY.")

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
