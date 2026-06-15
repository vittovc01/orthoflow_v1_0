
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

def normalize_code(codice):
    s = str(codice or "").upper().strip()
    s = re.sub(r"[^A-Z0-9]", "", s)
    return s

def code_variants(codice):
    base = normalize_code(codice)
    variants = {base}
    if base.endswith("S"):
        variants.add(base[:-1])
    else:
        variants.add(base + "S")
    return variants

def prezzo_per(conn, codice_cliente, codice, linea, data_intervento):
    """
    Matching prezzo intelligente:
    confronta codici anche se nell'offerta sono scritti con/senza punti o con/senza S finale.
    Esempi considerati compatibili:
    413.050s, 413.050S, 413050, 413050S.
    """
    target_variants = code_variants(codice)
    rows = conn.execute("""
        SELECT p.codice, p.prezzo
        FROM offerte_prezzi p
        JOIN offerte_header h ON h.id=p.offerta_id
        JOIN offerte_clienti c ON c.offerta_id=h.id
        WHERE c.codice_cliente=? AND h.linea=?
        AND (h.data_inizio IS NULL OR h.data_inizio='' OR h.data_inizio<=?)
        AND (h.data_fine IS NULL OR h.data_fine='' OR h.data_fine>=?)
        ORDER BY h.data_inizio DESC
    """, (codice_cliente, linea, data_intervento, data_intervento)).fetchall()

    for r in rows:
        if normalize_code(r["codice"]) in target_variants:
            return float(r["prezzo"]) if r["prezzo"] is not None else None
    return None


def detect_origine(conn, codice, lotto):
    lotto_s = str(lotto or "").strip()
    variants = list(code_variants(codice))
    placeholders = ",".join(["?"] * len(variants))
    rows = conn.execute(f"SELECT codice, origine FROM magazzino WHERE lotto=? ORDER BY id DESC", (lotto_s,)).fetchall()
    for r in rows:
        if normalize_code(r["codice"]) in variants:
            return r["origine"]
    return "NON TROVATO"

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

    target_variants = code_variants(codice)
    rows = conn.execute("""
        SELECT p.codice
        FROM offerte_prezzi p
        JOIN offerte_header h ON h.id=p.offerta_id
        JOIN offerte_clienti c ON c.offerta_id=h.id
        WHERE c.codice_cliente=? AND h.linea=?
        LIMIT 50000
    """, (codice_cliente, linea)).fetchall()

    for r in rows:
        if normalize_code(r["codice"]) in target_variants:
            return issues

    sample = ", ".join([str(r["codice"]) for r in rows[:8]])
    issues.append(f"Codice {codice} non presente nei prezzi offerta. Formati cercati: {', '.join(sorted(target_variants))}. Esempi offerta: {sample}")
    return issues




def normalize_code_exact(codice):
    """
    Normalizzazione sicura J&J:
    - rimuove spazi, punti, trattini solo per confrontare formati diversi
      es. 413.050S == 413050S
    - NON aggiunge e NON rimuove S finale
      quindi 413.050S != 413.050
    """
    s = str(codice or "").upper().strip()
    s = re.sub(r"[^A-Z0-9]", "", s)
    return s

def same_jj_code(a, b):
    return normalize_code_exact(a) == normalize_code_exact(b)

def prezzo_per(conn, codice_cliente, codice, linea, data_intervento):
    """
    Matching prezzo J&J Safe Match:
    coincidono cliente + linea + codice articolo identico.
    La S finale resta discriminante:
    413.050S != 413.050
    """
    target = normalize_code_exact(codice)
    rows = conn.execute("""
        SELECT p.codice, p.prezzo
        FROM offerte_prezzi p
        JOIN offerte_header h ON h.id=p.offerta_id
        JOIN offerte_clienti c ON c.offerta_id=h.id
        WHERE c.codice_cliente=? AND h.linea=?
        AND (h.data_inizio IS NULL OR h.data_inizio='' OR h.data_inizio<=?)
        AND (h.data_fine IS NULL OR h.data_fine='' OR h.data_fine>=?)
        ORDER BY h.data_inizio DESC
    """, (codice_cliente, linea, data_intervento, data_intervento)).fetchall()

    for r in rows:
        if normalize_code_exact(r["codice"]) == target:
            return float(r["prezzo"]) if r["prezzo"] is not None else None
    return None

def detect_origine(conn, codice, lotto):
    """
    Cerca origine in magazzino rispettando S finale.
    Punti/spazi possono differire, ma S non viene mai ignorata.
    """
    lotto_s = str(lotto or "").strip()
    target = normalize_code_exact(codice)
    rows = conn.execute("SELECT codice, origine FROM magazzino WHERE lotto=? ORDER BY id DESC", (lotto_s,)).fetchall()
    for r in rows:
        if normalize_code_exact(r["codice"]) == target:
            return r["origine"]
    return "NON TROVATO"

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

    target = normalize_code_exact(codice)
    rows = conn.execute("""
        SELECT p.codice
        FROM offerte_prezzi p
        JOIN offerte_header h ON h.id=p.offerta_id
        JOIN offerte_clienti c ON c.offerta_id=h.id
        WHERE c.codice_cliente=? AND h.linea=?
        LIMIT 50000
    """, (codice_cliente, linea)).fetchall()

    for r in rows:
        if normalize_code_exact(r["codice"]) == target:
            return issues

    # Cerca codici simili solo come suggerimento, NON come match.
    no_s_target = target[:-1] if target.endswith("S") else target + "S"
    similar = []
    for r in rows[:50000]:
        rc = normalize_code_exact(r["codice"])
        if rc == no_s_target:
            similar.append(str(r["codice"]))

    if similar:
        issues.append(
            f"Prezzo non agganciato: trovato codice simile {similar[0]}, "
            f"ma differisce per S sterile/non sterile. {codice} ≠ {similar[0]}"
        )
    else:
        sample = ", ".join([str(r["codice"]) for r in rows[:8]])
        issues.append(
            f"Codice {codice} non presente nell'offerta per cliente {codice_cliente}, linea {linea}. "
            f"Esempi offerta: {sample}"
        )

    return issues
