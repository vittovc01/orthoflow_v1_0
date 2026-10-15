"""Framework-free validation/evidence contract shared by Streamlit and mobile.

Scores describe available evidence, NOT calibrated probabilities of correctness.
No function in this module writes stock, files, or database records.
"""
import calendar
import re
from datetime import date, datetime

FIELDS = ('code', 'lot', 'expiry', 'description', 'gtin')
ALIASES = {'code':'codice','lot':'lotto','expiry':'scadenza','description':'descrizione'}


def exact_code(value):
    """Normalize catalogue lookup punctuation only; never replace OCR characters."""
    return re.sub(r'[^A-Z0-9]', '', str(value or '').upper())


def normalize_expiry(value):
    """Return date, source precision. Month-only values stay explicitly month-only."""
    text = str(value or '').strip()
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d'):
        try:
            return datetime.strptime(text, fmt).date().isoformat(), 'day'
        except ValueError:
            pass
    for fmt in ('%Y-%m', '%m/%Y', '%m-%Y', '%Y/%m'):
        try:
            value = datetime.strptime(text, fmt)
            return date(value.year, value.month, calendar.monthrange(value.year,value.month)[1]).isoformat(), 'month'
        except ValueError:
            pass
    return None, None


def assess_label(item, *, catalog=None, today=None, soon_days=90):
    """Keep critical conflicts empty; expose GS1 proposals separately for review."""
    from label_pipeline import gs1_parse
    today = today or date.today()
    fields, issues = {}, []
    barcodes = []
    for observation in item.get('barcodes') or []:
        # Never trust a client-supplied decoded object without reparsing its raw GS1.
        if not observation.get('raw'):
            issues.append('Payload GS1 originale assente: evidenza non verificabile')
            continue
        decoded = gs1_parse(observation['raw'])
        if decoded.get('error'):
            issues.append('GS1 non valido: ' + decoded['error'])
        else:
            barcodes.append(decoded)
    for name in FIELDS:
        value = item.get(name, item.get(ALIASES.get(name)))
        value = str(value).strip() if value is not None else None
        value = value or None
        reads = [r.get(name) for r in item.get('ocr_reads') or [] if r.get(name)]
        decoded = sorted({str(b[name]) for b in barcodes if b.get(name)}) if name in ('lot','expiry','gtin') else []
        method, status, score = 'missing', 'missing', 0.0
        observations = {'ocr':reads,'datamatrix':decoded}
        if value:
            method, status, score = 'ocr', 'unverified', .45
            if len(reads)>=2 and all(str(r).strip()==value for r in reads):
                method, status, score = 'ocr_consensus', 'agreement', .75
            if name=='code' and item.get('local_ref_evidence',{}).get('candidates')==[value]:
                method, status, score = 'ocr_consensus_local', 'agreement', .85
        if len(decoded)>1 or (decoded and reads and any(str(r).strip()!=decoded[0] for r in reads)):
            status, score = 'conflict', 0.0
            # Preserve the verified payload candidate, never silently substitute it.
            if name!='gtin':
                value = None
            method = 'datamatrix_ocr_conflict'
        elif len(decoded)==1:
            if value and value!=decoded[0]:
                status, score, value, method = 'conflict', 0.0, None, 'datamatrix_ocr_conflict'
            elif value:
                method = 'datamatrix_ocr' if reads else 'datamatrix'
                status, score = 'agreement' if reads else 'decoded', .95 if reads else .9
        precision = None
        if name=='expiry' and value:
            normalized, precision = normalize_expiry(value)
            if not normalized:
                status, score = 'invalid', 0.0
            else:
                value = normalized
                if precision=='month' or any(b.get('ais',{}).get('17','')[-2:]=='00' for b in barcodes):
                    precision, status = 'month', 'unverified'
                    issues.append('Scadenza con precisione mese: confermare sul documento')
        if name=='code' and value:
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9. /-]*',value) or re.fullmatch(r'\d{14}',value):
                status, score = 'invalid', 0.0
            if catalog is not None and exact_code(value) not in {exact_code(c) for c in catalog}:
                issues.append('REF non presente nel catalogo: ' + value)
                status = 'unknown_catalogue'
        if name=='gtin' and value:
            if gs1_parse('(01)'+value).get('error'):
                status, score = 'invalid', 0.0
        if name in item.get('manual_fields',[]) and value and status not in {'invalid','unknown_catalogue'}:
            method, status, score = 'manual', 'reviewed', 1.0
        if status in {'missing','conflict','invalid','unverified','unknown_catalogue'}:
            issues.append(name + ': ' + status)
        fields[name] = {'value':value,'method':method,'status':status,'score':score,
                        'precision':precision,'observations':observations}
    expiry = fields['expiry']['value']
    expiry_status = 'unknown'
    if expiry and fields['expiry']['status']!='invalid':
        days = (date.fromisoformat(expiry)-today).days
        expiry_status = 'expired' if days<0 else 'soon' if days<=soon_days else 'valid'
        if expiry_status!='valid':
            issues.append('Prodotto scaduto' if days<0 else f'Prodotto in scadenza entro {soon_days} giorni')
    box = item.get('bbox') or []
    if len(box)==4 and (min(box[:2])<=0 or max(box[2:])>=1000):
        issues.append('Etichetta sul bordo: verificare completezza o acquisire una nuova foto')
    return {'fields':fields,'issues':list(dict.fromkeys(issues)),
            'needs_review':bool(issues),'expiry_status':expiry_status,
            'score_semantics':'evidence_strength_not_probability'}


def canonical_item(row):
    item = dict(row)
    for name, alias in ALIASES.items():
        item[name] = row.get(name, row.get(alias))
    return item


def build_review(extraction, *, catalog=None, today=None, soon_days=90):
    """JSON contract; edits belong in confirmed records, never overwrite extraction."""
    labels = []
    for original in extraction.get('items') or []:
        item = canonical_item(original)
        labels.append({**item, 'assessment':assess_label(item,catalog=catalog,today=today,soon_days=soon_days)})
    return {**extraction, 'items':labels,'review_required':True,
            'physical_label_count':len(labels),'soon_days':soon_days,
            'catalogue_checked':catalog is not None}


def aggregate_review(rows):
    """Same exact REF/lot -> one row; conflicting expiry requires correction first."""
    groups, ids = {}, set()
    for original in rows:
        row = canonical_item(original)
        if row.get('escludi_riga'):
            continue
        label_id = row.get('label_id')
        if not label_id or label_id in ids:
            raise ValueError('Identità fisica assente o ripetuta')
        ids.add(label_id)
        if not row.get('code') or not str(row.get('lot') or '').strip():
            raise ValueError('Codice e lotto obbligatori per aggregare etichette di impianto')
        if len(str(row['lot']).strip())>20 or any(ord(c)<32 for c in str(row['lot'])):
            raise ValueError('Formato lotto non valido')
        expiry, precision = normalize_expiry(row.get('expiry'))
        if not expiry or precision!='day':
            raise ValueError('Scadenza completa da confermare')
        key = (str(row['code']).strip(),str(row['lot']).strip())
        if key in groups:
            if groups[key]['expiry']!=expiry:
                raise ValueError('Scadenze discordanti per lo stesso REF/lotto: verifica necessaria')
            groups[key]['quantity']+=1
            groups[key]['label_ids'].append(label_id)
        else:
            groups[key] = dict(code=key[0],lot=key[1],expiry=expiry,
                               description=row.get('description'),quantity=1,label_ids=[label_id])
    return list(groups.values())


def validate_confirmation(extraction, confirmed, *, physical_count, count_verified, actor):
    """Run again in the trusted server; UI/HTTP booleans alone are insufficient."""
    if (not isinstance(actor,str) or not actor.strip() or count_verified is not True
            or type(physical_count) is not int or physical_count<=0 or physical_count!=len(confirmed)):
        raise ValueError('Utente e conteggio fisico verificato obbligatori')
    if any(d.get('status')=='failed' for d in extraction.get('documents',[]) if isinstance(d,dict)):
        raise ValueError('Documento non analizzato: ripetere la lettura prima della conferma')
    expected = {i.get('label_id') for i in extraction.get('items') or []}
    actual = [r.get('label_id') for r in confirmed]
    # Added manual physical labels must be explicitly represented in extraction.
    if None in expected or set(actual)!=expected or len(set(actual))!=len(actual):
        raise ValueError('Etichette mancanti, aggiunte senza evidenza o duplicate')
    for row in confirmed:
        if row.get('verificata',row.get('reviewed',False)) is not True:
            raise ValueError('Verifica individuale richiesta')
        if row.get('escludi_riga'):
            continue
        item = canonical_item(row)
        if isinstance(row.get('quantita',row.get('quantity',1)),bool) or row.get('quantita',row.get('quantity',1)) != 1:
            raise ValueError('Una etichetta fisica rappresenta un solo pezzo')
        if not item.get('code') or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9. /-]*',str(item['code'])) or re.fullmatch(r'\d{14}',str(item['code'])):
            raise ValueError('REF non valido')
        gtin = item.get('gtin')
        if gtin:
            from label_pipeline import gs1_parse
            if gs1_parse('(01)'+str(gtin)).get('error'):
                raise ValueError('GTIN non valido')
    return aggregate_review(confirmed)


def merge_confirmed_fields(originals, edits):
    """Merge only editable fields; keep identity, barcode and crop evidence server-side."""
    source = {r['label_id']:r for r in originals}
    if len(source)!=len(originals):
        raise ValueError('Identità fisiche originali ripetute')
    allowed = set(FIELDS) | set(ALIASES.values()) | {'label_id','quantita','quantity',
        'verificata','reviewed','escludi_riga','senza_lotto','jnj_verificato_manualmente',
        'conto_deposito_struttura','produttore'}
    merged = []
    seen = set()
    for edit in edits:
        key = edit.get('label_id')
        if key not in source or key in seen:
            raise ValueError('Etichetta modificata non corrispondente agli originali')
        seen.add(key)
        row = {**source[key], **{k:v for k,v in edit.items() if k in allowed}}
        for name, alias in ALIASES.items():
            if alias in edit:
                row[name] = row[alias] = edit[alias]
            elif name in edit:
                row[name] = row[alias] = edit[name]
        merged.append(row)
    return merged
