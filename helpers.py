
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


def normalize_text_match(s):
    import re, unicodedata
    s = str(s or "").upper().strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def resolve_cliente_from_structure(conn, detected_name):
    """
    Ritorna dict con codice_cliente, descrizione, metodo, score.
    Cerca prima negli alias, poi nell'anagrafica clienti con matching semplice.
    """
    target = normalize_text_match(detected_name)
    if not target:
        return None

    # 1 alias exact/contains
    rows = conn.execute("SELECT * FROM alias_strutture ORDER BY priorita ASC").fetchall()
    best = None
    for r in rows:
        alias = normalize_text_match(r["alias"])
        if not alias:
            continue
        score = 0
        if alias == target:
            score = 100
        elif alias in target or target in alias:
            score = 90
        else:
            alias_words = set(alias.split())
            target_words = set(target.split())
            if alias_words:
                score = int(100 * len(alias_words & target_words) / len(alias_words | target_words))
        if score >= 65 and (best is None or score > best["score"]):
            best = {
                "codice_cliente": r["codice_cliente"],
                "descrizione": r["descrizione_cliente"] or "",
                "metodo": "alias",
                "score": score
            }
    if best:
        return best

    # 2 anagrafica clienti
    rows = conn.execute("SELECT codice_cliente, descrizione FROM clienti").fetchall()
    best = None
    for r in rows:
        desc = normalize_text_match(r["descrizione"])
        score = 0
        if desc == target:
            score = 100
        elif desc and (desc in target or target in desc):
            score = 85
        else:
            dw = set(desc.split())
            tw = set(target.split())
            if dw:
                score = int(100 * len(dw & tw) / len(dw | tw))
        if score >= 55 and (best is None or score > best["score"]):
            best = {
                "codice_cliente": r["codice_cliente"],
                "descrizione": r["descrizione"],
                "metodo": "anagrafica",
                "score": score
            }
    return best

def diagnose_price(conn, codice_cliente, codice, linea, data_intervento):
    issues = []
    if not codice_cliente:
        issues.append("Codice cliente non risolto dalla struttura")
        return issues
    linked = conn.execute("""
        SELECT h.id, h.nome_offerta, h.linea
        FROM offerte_header h
        JOIN offerte_clienti c ON c.offerta_id=h.id
        WHERE c.codice_cliente=? AND h.linea=?
    """, (codice_cliente, linea)).fetchall()
    if not linked:
        issues.append(f"Nessuna offerta collegata al cliente {codice_cliente} per linea {linea}")
        return issues
    found_code = conn.execute("""
        SELECT p.codice
        FROM offerte_prezzi p
        JOIN offerte_header h ON h.id=p.offerta_id
        JOIN offerte_clienti c ON c.offerta_id=h.id
        WHERE c.codice_cliente=? AND h.linea=? AND p.codice=?
        LIMIT 1
    """, (codice_cliente, linea, codice)).fetchone()
    if not found_code:
        issues.append(f"Codice {codice} non presente nei prezzi offerta per cliente {codice_cliente} linea {linea}")
    return issues


def prezzo_per_flessibile(conn, codice_cliente, codice, linea, data_intervento):
    codice = str(codice or "").strip()
    variants = [codice]
    if codice.upper().endswith("S"):
        variants.append(codice[:-1])
    else:
        variants.append(codice + "S")
    placeholders = ",".join(["?"] * len(variants))
    query = f"""
    SELECT p.prezzo
    FROM offerte_prezzi p
    JOIN offerte_header h ON h.id=p.offerta_id
    JOIN offerte_clienti c ON c.offerta_id=h.id
    WHERE c.codice_cliente=? AND h.linea=? AND p.codice IN ({placeholders})
    AND (h.data_inizio IS NULL OR h.data_inizio='' OR h.data_inizio<=?)
    AND (h.data_fine IS NULL OR h.data_fine='' OR h.data_fine>=?)
    ORDER BY CASE WHEN p.codice=? THEN 0 ELSE 1 END
    LIMIT 1
    """
    params = [codice_cliente, linea] + variants + [data_intervento, data_intervento, codice]
    r = conn.execute(query, params).fetchone()
    return float(r["prezzo"]) if r else None
