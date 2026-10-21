"""Editable review contract. Technical identifiers never block an operator's work.

No database, filesystem or image writes. Callers own session state and persist the
correction log with the intervention's existing audit transaction, not OCR archive.
"""
import math
import re
from datetime import datetime, timezone
from uuid import uuid4

ALIASES = {'code':'codice','lot':'lotto','expiry':'scadenza','quantity':'quantita'}
EDITABLE = {'codice','lotto','scadenza','quantita','descrizione','produttore',
            'escludi_riga','conto_deposito_struttura','jnj_verificato_manualmente','senza_lotto'}


def text_value(value):
    if value is None:
        return ''
    text = str(value).strip()
    return '' if text.lower() in {'nan','nat','none','null','<na>'} else text


def product_ref(value):
    """Remove a printed REF field marker, preserving product punctuation/suffixes.

    A separator is required: codes beginning REFERENCE or REF123 stay intact.
    """
    text = text_value(value).upper()
    return re.sub(r'^REF(?:\s*[:：]\s*|\s+)', '', text).strip()


def technical_gtin(value):
    text = text_value(value)
    return text or None


def canonical_values(row):
    result = dict(row)
    for field, alias in ALIASES.items():
        value = row.get(alias, row.get(field))
        result[alias] = (value if text_value(value) else None) if field=='quantity' else text_value(value)
        if field=='code':result[alias]=product_ref(result[alias])
        if field=='expiry' and result[alias]:
            for fmt in ('%Y-%m-%d','%d/%m/%Y','%d-%m-%Y','%Y/%m/%d'):
                try:
                    result[alias]=datetime.strptime(result[alias],fmt).date().isoformat()
                    break
                except ValueError:
                    pass
        result[field] = result[alias]
    for name in ('descrizione','produttore'):
        result[name]=text_value(row.get(name))
    for name in ('escludi_riga','senza_lotto','conto_deposito_struttura','jnj_verificato_manualmente'):
        result[name]=text_value(row.get(name)).lower() in {'true','1'}
    result['gtin'] = technical_gtin(row.get('gtin'))
    return result


def row_name(row):
    row = canonical_values(row)
    return f"{row['codice'] or 'REF mancante'}, lotto {row['lotto'] or 'mancante'}"


def quantity_value(value):
    if isinstance(value, bool) or text_value(value).lower() in {'true','false'} or not text_value(value):
        return None
    try:
        number = float(value)
        return int(number) if math.isfinite(number) and number>0 and number.is_integer() else None
    except (ValueError, TypeError, OverflowError):
        return None


def row_errors(row):
    row = canonical_values(row)
    if row.get('escludi_riga'):
        return []
    problems = []
    code, lot = row['codice'], row['lotto']
    if not code:
        problems.append('REF mancante')
    elif not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9. /-]*',code) or re.fullmatch(r'\d{14}',code):
        problems.append('REF non valido')
    if not lot:
        problems.append('lotto mancante')
    elif len(lot)>20 or any(ord(c)<32 for c in lot):
        problems.append('lotto non valido')
    from ocr_review import normalize_expiry
    expiry, precision = normalize_expiry(row['scadenza'])
    if not row['scadenza']:
        problems.append('scadenza mancante')
    elif not expiry or precision!='day':
        problems.append('scadenza non valida: indicare giorno, mese e anno')
    if quantity_value(row['quantita']) is None:
        problems.append('quantità non valida: inserire un intero maggiore di zero')
    return [f'{row_name(row)}: {problem}' for problem in problems]


def expected_label_count(rows):
    return sum(not canonical_values(r)['escludi_riga'] for r in rows)


def count_warning(rows, reported):
    expected = expected_label_count(rows)
    difference = int(reported)-expected
    if not difference:
        return None
    return f'Conteggio discordante: {int(reported)} etichette contate, {expected} righe incluse; differenza {difference:+d}. Controlla le righe aggiunte, eliminate o ripetute.'


def catalogue_warning(row, catalog):
    """GTIN supports a cross-check; never substitutes or invalidates a typed REF."""
    from catalog_import import valid_gtin
    row = canonical_values(row)
    gtin, code = row['gtin'], row['codice']
    if not gtin or not valid_gtin(gtin) or not isinstance(catalog,dict) or not catalog.get(gtin):
        warning = 'REF non confrontato con il catalogo'
    else:
        from ocr_review import exact_code
        warning = None if exact_code(catalog[gtin])==exact_code(code) else 'REF diverso dal catalogo: controlla il valore digitato'
    if isinstance(catalog,dict) and any(f in row.get('manual_fields',[]) for f in ('code','codice')):
        from ocr_review import exact_code
        if code and exact_code(code) not in {exact_code(v) for v in catalog.values()}:
            warning = (warning+'; ' if warning else '')+'REF digitato non presente nel catalogo'
    return f'{row_name(row)}: {warning}' if warning else None


def apply_review_edits(originals, edits, *, actor, timestamp=None):
    """Assign manual IDs server-side, retain hidden evidence, audit every delta.

    Missing rows are deletions; missing IDs are additions. Existing IDs cannot be
    duplicated or invented by a client. Actor comes from the authenticated session.
    """
    if not text_value(actor):
        raise ValueError('Utente della revisione mancante')
    timestamp = timestamp or datetime.now(timezone.utc).isoformat()
    source = {r['label_id']:canonical_values(r) for r in originals}
    if len(source)!=len(originals):
        raise ValueError('Identità delle righe ripetuta')
    output, logs, seen = [], [], set()
    def record(label_id, operation, field, before, after):
        logs.append(dict(label_id=label_id,operation=operation,field=field,
                         original=before,corrected=after,method='manuale',user=str(actor),timestamp=timestamp))
    for edit in edits:
        key = text_value(edit.get('label_id'))
        if key and (key not in source or key in seen):
            raise ValueError('Riga modificata non corrispondente alla lista')
        new = not key
        key = key or f'manual:{uuid4().hex}'
        seen.add(key)
        base = source.get(key,dict(label_id=key,manual_entry=True,crop_data_url=None,gtin=None,
                                    quantity=1,quantita=1,verificata=False))
        supplied = {k:v for k,v in edit.items() if k in EDITABLE}
        for field, alias in ALIASES.items():
            if field in edit and alias not in supplied:
                supplied[alias]=edit[field]
        row = canonical_values({**base,**supplied})
        row['label_id']=key
        # Normalize valid values; leave invalid ones visible so only their row is marked.
        quantity=quantity_value(row['quantita'])
        if quantity is not None:
            row['quantity']=row['quantita']=quantity
        for name in ('escludi_riga','senza_lotto','conto_deposito_struttura','jnj_verificato_manualmente'):
            row[name]=text_value(row.get(name)).lower() in {'true','1'}
        if row['lotto']:
            row['senza_lotto']=False
        fields=set(row.get('manual_fields') or [])
        for field in sorted(EDITABLE):
            before=base.get(field)
            after=row.get(field)
            if field in ('codice','lotto','scadenza','descrizione','produttore'):
                before,after=text_value(before),text_value(after)
            if field in ('escludi_riga','senza_lotto','conto_deposito_struttura','jnj_verificato_manualmente'):
                before=bool(before) if text_value(before) else False
            if new or before!=after:
                record(key,'add' if new else 'update',field,None if new else before,after)
                fields.add(next((f for f,a in ALIASES.items() if a==field),field))
        row['manual_fields']=sorted(fields)
        output.append(row)
    for key, row in source.items():
        if key not in seen:
            record(key,'delete','row',{a:row.get(a) for a in ALIASES.values()},None)
    return output, logs
