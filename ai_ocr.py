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
Sei un motore OCR specializzato su scarichi sala operatoria ortopedici Johnson & Johnson / DePuy Synthes. Devi estrarre SEMPRE la struttura/clinica se compare sul documento.
Leggi nome struttura/clinica, cartella clinica, chirurgo, data, codici, lotti, scadenze e produttore.
Per ogni etichetta cerca:
- REF / REF. / CODICE / CAT = codice prodotto
- LOT / LOTTO / BATCH = lotto
- EXP / SCAD / SCADENZA / USE BY = scadenza
Non confondere intestazioni ospedaliere o parole del modulo con lotti.
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
    """
    OCR gratuito: estrazione lotto prudente.
    Evita parole del modulo lette male come IERA, DIRETTORE, OSPEDALE ecc.
    Accetta preferibilmente stringhe vicino a LOT/LOTTO/BATCH e con almeno un numero.
    """
    lots = []
    up = text.upper()

    blacklist = {
        "DIRETTORE", "OSPEDALE", "OSPEDALIERA", "AZIENDA", "UNIVERSITARIA",
        "UNIVE", "IERA", "SALA", "CHIRURGO", "PAZIENTE", "DATA", "CODICE",
        "DESCRIZIONE", "QUANTITA", "SCADENZA", "LOTTO", "PRODUTTORE"
    }

    # Lotto dopo etichetta esplicita
    for m in re.findall(r"(?:LOT|LOTTO|BATCH|L\.?)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-]{3,20})", up):
        clean = m.strip(" -:;,.")
        if clean not in blacklist and any(ch.isdigit() for ch in clean):
            if clean not in lots:
                lots.append(clean)

    # Lotto alfanumerico plausibile, sempre con numeri
    for m in re.findall(r"\b([A-Z]{1,4}\d{4,14}[A-Z0-9]{0,6})\b", up):
        clean = m.strip(" -:;,.")
        if clean not in blacklist and any(ch.isdigit() for ch in clean):
            if clean not in lots:
                lots.append(clean)

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


def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", str(line or "").strip())

def _nearby_value(lines, idx, labels, max_lookahead=3):
    """
    Cerca valore vicino a etichette tipo REF/LOT/EXP nella stessa riga o righe successive.
    """
    for j in range(idx, min(len(lines), idx + max_lookahead + 1)):
        line = lines[j].upper()
        for lab in labels:
            if lab in line:
                # valore dopo label nella stessa riga
                parts = re.split(rf"{lab}\s*[:\-]?", line, maxsplit=1)
                if len(parts) > 1:
                    val = parts[1].strip(" :;-")
                    if val:
                        return val
                # prima riga successiva non vuota
                for k in range(j + 1, min(len(lines), j + max_lookahead + 1)):
                    val = lines[k].strip()
                    if val:
                        return val
    return None

def _clean_code(value: str):
    if not value:
        return None
    up = value.upper()
    pats = [
        r"\b\d{2}\.\d{3}\.\d{3,4}S?\b",
        r"\b\d{3}\.\d{3,4}S?\b",
        r"\b\d{2}\.\d{4}\.\d{3,4}S?\b",
    ]
    for p in pats:
        m = re.search(p, up)
        if m:
            return m.group(0)
    return None

def _clean_lot(value: str):
    if not value:
        return None
    up = value.upper()
    blacklist = {
        "DIRETTORE", "OSPEDALE", "OSPEDALIERA", "AZIENDA", "UNIVERSITARIA",
        "UNIVE", "IERA", "SALA", "CHIRURGO", "PAZIENTE", "DATA", "CODICE",
        "DESCRIZIONE", "QUANTITA", "SCADENZA", "LOTTO", "PRODUTTORE",
        "REF", "LOT", "EXP", "STERILE", "SYNTHES", "DEPUY", "JOHNSON"
    }
    candidates = re.findall(r"\b[A-Z0-9][A-Z0-9\-]{3,20}\b", up)
    for c in candidates:
        if c in blacklist:
            continue
        if any(ch.isdigit() for ch in c) and not _clean_code(c):
            return c
    return None

def _clean_expiry(value: str):
    if not value:
        return None
    up = value.upper()
    pats = [
        r"\b20\d{2}[-/\.]\d{1,2}[-/\.]\d{1,2}\b",
        r"\b\d{1,2}[-/\.]\d{1,2}[-/\.]20\d{2}\b",
        r"\b\d{1,2}[-/\.]20\d{2}\b",
        r"\b20\d{2}[-/\.]\d{1,2}\b",
    ]
    for p in pats:
        m = re.search(p, up)
        if m:
            return m.group(0)
    return None

def _extract_structured_items(text: str):
    """
    Estrazione specializzata per etichette ortopediche J&J/DePuy/Synthes.
    Cerca codici prodotto e poi associa LOT/EXP nelle righe vicine.
    """
    raw_lines = [_normalize_line(x) for x in text.splitlines()]
    lines = [x for x in raw_lines if x]
    items = []

    code_positions = []
    for i, line in enumerate(lines):
        code = _clean_code(line)
        if code:
            code_positions.append((i, code))

    # Se REF è su riga separata, cerca codice nelle 3 righe successive
    for i, line in enumerate(lines):
        up = line.upper()
        if any(label in up for label in ["REF", "REF.", "CAT", "CODICE"]):
            val = _nearby_value(lines, i, ["REF", "REF.", "CAT", "CODICE"], 3)
            code = _clean_code(val or "")
            if code and all(code != c for _, c in code_positions):
                code_positions.append((i, code))

    seen = set()
    for idx, code in code_positions:
        if code in seen:
            continue
        seen.add(code)

        window = "\n".join(lines[max(0, idx-4): min(len(lines), idx+8)])
        lot_val = _nearby_value(lines, max(0, idx-4), ["LOT", "LOTTO", "BATCH"], 12)
        exp_val = _nearby_value(lines, max(0, idx-4), ["EXP", "SCAD", "SCADENZA", "USE BY"], 12)

        lot = _clean_lot(lot_val or window)
        expiry = _clean_expiry(exp_val or window)

        # produttore nel blocco vicino
        up_window = window.upper()
        is_jnj = any(w in up_window or w in text.upper() for w in ["DEPUY", "SYNTHES", "JOHNSON", "J&J"])

        items.append({
            "code": code,
            "lot": lot,
            "expiry": expiry,
            "description": "",
            "quantity": 1,
            "manufacturer": "DePuy Synthes" if is_jnj else None,
            "is_jnj_depuy_synthes": is_jnj,
            "is_sterile": code.upper().endswith("S"),
            "source_text": window[:1000],
            "confidence": 0.70 if lot or expiry else 0.55,
            "warning": "" if lot and expiry else "Controllare manualmente lotto/scadenza: OCR gratuito."
        })

    return items

def _free_ocr_result(path: str, mode: str):
    p = Path(path)
    text = _ocr_pdf_text(path) if p.suffix.lower() == ".pdf" else _ocr_image_text(path)
    up = text.upper()

    clinic = _guess_clinic(text)
    codes = _extract_codes(text)
    lots = _extract_lots(text)
    expiries = _extract_expiries(text)
    is_jnj = any(w in up for w in ["DEPUY", "SYNTHES", "JOHNSON", "J&J"])

    items = _extract_structured_items(text)

    # Fallback semplice se l'estrazione strutturata non trova nulla.
    if not items:
        items = []
        for i, code in enumerate(codes):
            items.append({
                "code": code,
                "lot": lots[i] if i < len(lots) and any(ch.isdigit() for ch in str(lots[i])) else None,
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


def ocr_engine_status() -> str:
    if openai_enabled():
        return "OpenAI AI OCR"
    if free_ocr_enabled():
        return "OCR gratuito Tesseract"
    return "OCR non attivo"
