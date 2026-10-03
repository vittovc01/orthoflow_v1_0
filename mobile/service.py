"""Server-only adapters to the same operational tables and stock RPC as the desktop."""
import io
import math
import re
import uuid
from datetime import date
from PIL import Image
from fastapi import HTTPException

BUCKET = 'orthoflow-impianti'
CERT = 'CERTIFICAZIONE_LAVAGGIO_DECONTAMINAZIONE'
MAX_FILE = 20 * 1024 * 1024


def rows(query):
    return query.execute().data or []


def code_key(code):
    return re.sub(r'[^A-Z0-9]', '', str(code or '').upper())


def allowed(row, permission):
    perms = set(row.get('permessi') or [])
    return row.get('ruolo') == 'Admin' or 'DIREZIONE' in perms or permission in perms


def require(row, permission):
    if not allowed(row, permission):
        raise HTTPException(403, 'Funzione non autorizzata per il tuo utente.')


def agent_access(row):
    if not any(allowed(row, p) for p in ('AGENTE', 'OPERATIVITA')):
        raise HTTPException(403, 'Scarico non autorizzato.')


def customers(sb, row):
    agent_access(row)
    q = sb.table('clienti').select('codice_cliente,descrizione,descrizione_cliente,agente')
    if row.get('ruolo') != 'Admin' and 'DIREZIONE' not in (row.get('permessi') or []):
        if 'AGENTE' in (row.get('permessi') or []):
            name = str(row.get('agente_nome') or '').strip()
            if not name:
                raise HTTPException(403, 'La Direzione deve collegare il tuo nome agente.')
            q = q.eq('agente', name)
    return rows(q.order('descrizione').limit(1000))


def mission(sb, row, mid):
    require(row, 'CORRIERE')
    found = rows(sb.table('missioni_corrieri').select('*').eq('id', mid).limit(1))
    if not found:
        raise HTTPException(404, 'Missione non disponibile.')
    m = found[0]
    # Directors can inspect; operational writes still identify the assigned courier.
    if row.get('ruolo') != 'Admin' and 'DIREZIONE' not in (row.get('permessi') or []):
        linked = rows(sb.table('corrieri').select('id').eq('user_id', row['id']).eq('attivo', True))
        if not any(c['id'] == m['corriere_id'] for c in linked):
            raise HTTPException(404, 'Missione non disponibile.')
    return m


def validated_file(data, filename, allow_pdf=False):
    if not data or len(data) > MAX_FILE:
        raise HTTPException(422, 'Ogni file deve essere compreso tra 1 byte e 20 MB.')
    if allow_pdf and data.startswith(b'%PDF-'):
        from pypdf import PdfReader
        try:
            pdf = PdfReader(io.BytesIO(data))
            if pdf.is_encrypted or not 1 <= len(pdf.pages) <= 100:
                raise ValueError()
        except Exception as exc:
            raise HTTPException(422, 'PDF non valido, protetto o oltre 100 pagine.') from exc
        return data, 'application/pdf', '.pdf'
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.format not in ('JPEG', 'PNG', 'WEBP') or im.width * im.height > 40_000_000:
                raise ValueError()
            im.verify()
        # Re-encode: strip EXIF/embedded content. PDFs retain the signed source bytes.
        with Image.open(io.BytesIO(data)) as im:
            out = io.BytesIO()
            im.convert('RGB').save(out, format='JPEG', quality=92)
            return out.getvalue(), 'image/jpeg', '.jpg'
    except Exception as exc:
        raise HTTPException(422, 'Immagine non valida. Usa JPG, PNG, WEBP oppure PDF dove previsto.') from exc


def upload(sb, folder, data, mime, ext):
    path = f'{folder}/{uuid.uuid4().hex}{ext}'
    sb.storage.from_(BUCKET).upload(path, data, {'content-type': mime, 'upsert': 'false'})
    return path


def prices(sb, customer, line):
    result = {}
    links = rows(sb.table('offerte_clienti').select('offerta_id').eq('codice_cliente', customer).order('id'))
    for link in links:
        head = rows(sb.table('offerte_header').select('linea').eq('id', link['offerta_id']).limit(1))
        if not head or str(head[0].get('linea') or '').upper() != line:
            continue
        offset = 0
        while True:
            batch = rows(sb.table('offerte_prezzi').select('codice,prezzo').eq('offerta_id', link['offerta_id'])
                         .order('id').range(offset, offset + 499))
            if not batch:
                break
            for p in batch:
                if p.get('prezzo') is not None:
                    result.setdefault(code_key(p['codice']), (float(p['prezzo']), 'OFFERTA'))
            offset += len(batch)
    history = sb.rpc('prezzi_manuali_struttura', {'p_codice_cliente': customer, 'p_linea': line}).execute().data or []
    for p in history:
        result.setdefault(p['codice_normalizzato'], (float(p['prezzo']), 'MANUALE_MEMORIZZATO'))
    return result


def build_scarico(sb, row, body):
    agent_access(row)
    customer = next((c for c in customers(sb, row) if c['codice_cliente'] == body.customer_code), None)
    if not customer:
        raise HTTPException(403, 'Struttura non assegnata o non disponibile.')
    warehouses = rows(sb.table('magazzini').select('codice_magazzino').eq('codice_magazzino', body.warehouse).limit(1))
    if not warehouses:
        raise HTTPException(422, 'Magazzino non disponibile.')
    price_map = prices(sb, body.customer_code, body.line)
    priced = []
    can_price = allowed(row, 'AMMINISTRAZIONE')
    for r in body.items:
        code, lot = r.code.strip(), r.lot.strip()
        if not code or (not lot and not r.lotless) or (lot and r.lotless):
            raise HTTPException(422, 'Verifica codice e lotto: conferma senza lotto solo per i non sterili.')
        if r.structure_stock and body.customer_code != '9010013':
            raise HTTPException(422, 'Conto deposito struttura disponibile solo per Malzoni.')
        manufacturer = r.manufacturer.upper()
        is_jnj = any(s in manufacturer for s in ('JOHNSON', 'J&J', 'SYNTHES', 'DEPUY'))
        if manufacturer and not is_jnj and not r.verified:
            raise HTTPException(422, 'Conferma manualmente che il prodotto è nostro oppure elimina la riga.')
        price, source = price_map.get(code_key(code), (0, 'DA_VERIFICARE_DIREZIONE'))
        if r.manual_price is not None:
            if not can_price:
                raise HTTPException(403, 'Prezzi manuali riservati all’amministrazione.')
            price, source = r.manual_price, 'MANUALE'
        priced.append({'codice': code, 'lotto': lot, 'senza_lotto': r.lotless, 'quantita': r.quantity,
                       'descrizione': r.description, 'scadenza': r.expiry.isoformat() if r.expiry else None, 'produttore': r.manufacturer,
                       'validazione': 'J&J verificato manualmente' if r.verified else 'Da verificare' if not is_jnj else 'Validato J&J',
                       'conto_deposito_struttura': r.structure_stock, 'prezzo': price, 'prezzo_source': source})
    label = customer.get('descrizione') or customer.get('descrizione_cliente') or body.customer_code
    agent = str(row.get('agente_nome') or row['username'])
    header = {'data_intervento': body.procedure_date.isoformat(), 'codice_cliente': body.customer_code,
              'cliente': label, 'struttura': label, 'cartella_clinica': body.clinical_record,
              'chirurgo': body.surgeon, 'agente': agent, 'linea': body.line, 'magazzino_scarico': body.warehouse}
    return header, priced
