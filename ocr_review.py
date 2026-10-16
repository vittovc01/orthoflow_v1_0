"""Framework-free validation/evidence contract shared by Streamlit and mobile.

Scores describe available evidence, NOT calibrated probabilities of correctness.
No function in this module writes stock, files, or database records.
"""
from review_editor import text_value, technical_gtin
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
        value = text_value(value) or None
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
            if catalog is not None and not isinstance(catalog,dict) and exact_code(value) not in {exact_code(c) for c in catalog}:
                issues.append('REF non presente nel catalogo: ' + value)
                status = 'unknown_catalogue'
        if name=='gtin' and value:
            if gs1_parse('(01)'+value).get('error'):
                status, score = 'invalid', 0.0
        if name=='code' and value and item.get('ref_source')=='articoli_gtin':
            method, status, score = 'catalogue', 'mapped', .9
        if name in item.get('manual_fields',[]) and value and status not in {'invalid','unknown_catalogue'}:
            method, status, score = 'manual', 'reviewed', 1.0
        if status in {'missing','conflict','invalid','unverified','unknown_catalogue'}:
            issues.append(name + ': ' + status)
        fields[name] = {'value':value,'method':method,'status':status,'score':score,
                        'precision':precision,'observations':observations}
    if isinstance(catalog,dict):
        gtin=fields['gtin']['value']
        ref=catalog.get(gtin) if gtin else None
        if not gtin:
            issues.append('GTIN assente: confronto GTIN → REF non eseguibile')
        elif ref is None:
            issues.append('GTIN non presente in articoli_gtin: ' + gtin)
            fields['gtin']['status']='unknown_catalogue'
        elif fields['code']['value'] and exact_code(ref)!=exact_code(fields['code']['value']):
            issues.append('REF discordante da articoli_gtin: verificare, nessuna sostituzione automatica')
            fields['code']['status']='catalogue_warning'
        elif fields['code']['value']:
            fields['code']['catalogue_ref']=ref
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
    technical = [issue for issue in issues if any(token in issue for token in ('GTIN','GS1','gtin:', 'articoli_gtin'))]
    issues = [issue for issue in issues if issue not in technical]
    return {'fields':fields,'technical_warnings':technical,'issues':list(dict.fromkeys(issues)),
            'needs_review':bool(issues),'expiry_status':expiry_status,
            'score_semantics':'evidence_strength_not_probability'}


def canonical_item(row):
    item = dict(row)
    for name, alias in ALIASES.items():
        item[name] = row.get(name, row.get(alias))
    for name in ('code','lot','expiry','description'):
        item[name]=text_value(item.get(name)) or None
    item['gtin']=technical_gtin(item.get('gtin'))
    return item


def cross_photo_candidates(rows):
    """Identity equality is ambiguous: two physical stickers may share REF and lot."""
    groups = {}
    for original in rows:
        row = canonical_item(original)
        if row.get('escludi_riga') or row.get('document_index') is None:
            continue
        key = (exact_code(row.get('code')), str(row.get('lot') or '').strip())
        if all(key):
            groups.setdefault(key, []).append(row)
    return [ [r['label_id'] for r in group] for group in groups.values()
             if len({r['document_index'] for r in group}) > 1 ]


def build_review(extraction, *, catalog=None, today=None, soon_days=90):
    """JSON contract; edits belong in confirmed records, never overwrite extraction."""
    labels = []
    for original in extraction.get('items') or []:
        item = canonical_item(original)
        # A decoded technical GTIN can supply the REF; never overwrite an OCR
        # reading or a field the operator deliberately edited/cleared.
        from catalog_import import valid_gtin
        gtin=item.get('gtin')
        if (not item.get('code') and isinstance(catalog,dict) and gtin and valid_gtin(gtin)
                and catalog.get(gtin) and 'code' not in item.get('manual_fields',[])):
            item['ref_ocr_original']=item.get('code')
            item['code']=catalog[gtin]
            if 'codice' in item:item['codice']=item['code']
            item['ref_source']='articoli_gtin'
        labels.append({**item, 'assessment':assess_label(item,catalog=catalog,today=today,soon_days=soon_days)})
    return {**extraction, 'items':labels,'review_required':True,
            'cross_photo_candidates':cross_photo_candidates(labels),
            'physical_label_count':len(labels),'soon_days':soon_days,
            'catalogue_checked':catalog is not None,
            'missing_gtins':[{'label_id':r.get('label_id'),'gtin':r.get('gtin'),
                'reason':'assente' if not r.get('gtin') else 'non_in_catalogo'}
                for r in labels if not r.get('gtin') or (isinstance(catalog,dict) and r.get('gtin') not in catalog)]}


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
        from review_editor import quantity_value, row_errors, row_name
        problems=row_errors(row)
        if problems:raise ValueError('; '.join(problems))
        expiry, precision = normalize_expiry(row.get('expiry'))
        quantity=quantity_value(row.get('quantita',row.get('quantity',1)))
        key = (str(row['code']).strip(),str(row['lot']).strip())
        if key in groups:
            if groups[key]['expiry']!=expiry:
                raise ValueError(f'{row_name(row)}: Scadenze discordanti, correggere la riga')
            groups[key]['quantity']+=quantity
            groups[key]['label_ids'].append(label_id)
        else:
            groups[key] = dict(code=key[0],lot=key[1],expiry=expiry,
                               description=row.get('description'),quantity=quantity,label_ids=[label_id])
    return list(groups.values())


def validate_confirmation(extraction, confirmed, *, physical_count, count_verified, actor, duplicates_reviewed=False):
    """Global operator confirmation; GTIN and count discrepancy never block."""
    from label_pipeline import review_errors
    if not text_value(actor):
        raise ValueError('Utente della revisione mancante')
    if any(d.get('status')=='failed' for d in extraction.get('documents',[]) if isinstance(d,dict)):
        raise ValueError('Documento non analizzato: ripetere la lettura prima della conferma')
    expected = {i.get('label_id') for i in extraction.get('items') or []}
    actual = [r.get('label_id') for r in confirmed]
    if None in expected or set(actual)!=expected or len(set(actual))!=len(actual):
        raise ValueError('Etichette mancanti, aggiunte senza revisione o duplicate')
    problems=review_errors(confirmed,list(expected),physical_count,count_verified)
    if problems:raise ValueError('; '.join(problems))
    return aggregate_review(confirmed)


def merge_confirmed_fields(originals, edits):
    """Merge only editable fields; keep identity, barcode and crop evidence server-side."""
    source = {r['label_id']:r for r in originals}
    if len(source)!=len(originals):
        raise ValueError('Identità fisiche originali ripetute')
    allowed = (set(FIELDS)-{'gtin'}) | set(ALIASES.values()) | {'label_id','quantita','quantity',
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
