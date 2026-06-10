
from datetime import datetime, timedelta, time
from pathlib import Path
import pandas as pd
import re
from pypdf import PdfReader

JJ_WORDS = ["J&J", "JOHNSON", "DEPUY", "SYNTHES", "DE PUY"]

def save_file(upload):
    Path("uploads").mkdir(exist_ok=True)
    name = upload.name.replace("/", "_").replace("\\", "_")
    path = Path("uploads") / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{name}"
    path.write_bytes(upload.getbuffer())
    return str(path)

def validate_produttore(text):
    t = str(text or "").upper()
    if not t.strip():
        return "Marchio non letto"
    return "Validato J&J" if any(w in t for w in JJ_WORDS) else "Prodotto non J&J"

def is_sterile(codice):
    return str(codice).strip().upper().endswith("S")

def reintegro_date():
    now = datetime.now()
    return now.date() if now.time() <= time(12,0) else now.date() + timedelta(days=1)

def money(v):
    if pd.isna(v):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("€","").replace(" ","")
    if "," in s and "." in s:
        s = s.replace(".","").replace(",",".")
    elif "," in s:
        s = s.replace(",",".")
    try:
        return float(s)
    except:
        return None

def norm(df):
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df

def find_col(cols, keys):
    for k in keys:
        for c in cols:
            if k.lower() in str(c).lower():
                return c
    return None

def pdf_text(upload):
    reader = PdfReader(upload)
    return "\n".join([(p.extract_text() or "") for p in reader.pages])

def prezzo_per(conn, codice_cliente, codice, linea, data_intervento):
    q = """
    SELECT p.prezzo
    FROM offerte_prezzi p
    JOIN offerte_header h ON h.id=p.offerta_id
    JOIN offerte_clienti c ON c.offerta_id=h.id
    WHERE c.codice_cliente=? AND p.codice=? AND h.linea=?
    AND (h.data_inizio IS NULL OR h.data_inizio='' OR h.data_inizio<=?)
    AND (h.data_fine IS NULL OR h.data_fine='' OR h.data_fine>=?)
    ORDER BY h.data_inizio DESC
    LIMIT 1
    """
    r = conn.execute(q, (codice_cliente, codice, linea, data_intervento, data_intervento)).fetchone()
    return float(r["prezzo"]) if r else None

def detect_origine(conn, codice, lotto):
    r = conn.execute("SELECT origine FROM magazzino WHERE codice=? AND lotto=? ORDER BY id DESC LIMIT 1", (codice, lotto)).fetchone()
    return r["origine"] if r else "NON TROVATO"

def excel_bytes(sheets):
    import io
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="xlsxwriter") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, index=False, sheet_name=name[:31])
    return bio.getvalue()
