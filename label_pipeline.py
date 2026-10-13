"""Physical-label OCR: geometry precedes identity; no production writes."""
import base64
import calendar
import hashlib
import math
import re
from datetime import date
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps


def image_url(image):
    buf = BytesIO()
    image.save(buf, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


def render_pages(path):
    path = Path(path)
    if path.suffix.lower() == '.pdf':
        import fitz
        with fitz.open(path) as doc:
            if len(doc) > 12:
                raise ValueError('Massimo 12 pagine per analisi; dividere il documento.')
            return [Image.open(BytesIO(p.get_pixmap(matrix=fitz.Matrix(4, 4), alpha=False).tobytes('png'))).convert('RGB') for p in doc]
    with Image.open(path) as image:
        return [ImageOps.exif_transpose(image).convert('RGB')]


def overlap(a, b):
    intersection = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    areas = [(r[2]-r[0])*(r[3]-r[1]) for r in (a, b)]
    return intersection / min(areas) if min(areas) > 0 else 0


def unique_regions(regions):
    """Collapse geometrically equivalent crops, never equal REF/lot identities."""
    out = []
    for region in sorted(regions, key=lambda r: (r['page'], r['bbox'][1], r['bbox'][0])):
        box = region['bbox']
        if len(box) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in box):
            raise ValueError('Coordinate etichetta non valide')
        if not (0 <= box[0] < box[2] <= 1000 and 0 <= box[1] < box[3] <= 1000):
            raise ValueError('Ritaglio etichetta fuori pagina')
        if not any(r['page'] == region['page'] and overlap(r['bbox'], box) >= .85 for r in out):
            out.append(dict(region))
    return out


def crop_region(page, bbox):
    w, h = page.size
    return page.crop(tuple(round(v * (w if i % 2 == 0 else h) / 1000) for i, v in enumerate(bbox)))


def gs1_parse(raw):
    """Supported GS1 AIs only. Unknown/truncated payloads remain explicit errors."""
    text = raw.removeprefix(']d2').removeprefix(']C1')
    values = {}
    if '(' in text:
        matches = list(re.finditer(r'\((\d{2,4})\)', text))
        if not matches or matches[0].start() != 0:
            return {'error': 'GS1 non valido'}
        parts = [(m.group(1), text[m.end():matches[i+1].start() if i+1<len(matches) else len(text)]) for i,m in enumerate(matches)]
    else:
        parts = []
        while text:
            text = text.lstrip('\x1d')
            if not text:
                break
            ai, text = text[:2], text[2:]
            lengths = {'01': 14, '17': 6, '11': 6, '15': 6, '20': 2}
            if ai in lengths:
                n = lengths[ai]
                value, text = text[:n], text[n:]
                if len(value) != n or not value.isdigit():
                    return {'error': 'GS1 troncato'}
            elif ai in {'10', '21', '30', '91', '92', '93'}:
                value, sep, text = text.partition('\x1d')
                if not sep:
                    text = ''
            else:
                return {'error': 'AI GS1 non supportato: ' + ai}
            parts.append((ai, value))
    for ai, value in parts:
        if ai in values and values[ai] != value:
            return {'error': 'AI GS1 in conflitto'}
        if not value:
            return {'error': 'Valore GS1 vuoto'}
        values[ai] = value
    result = {'gtin': values.get('01'), 'lot': values.get('10'), 'expiry': None, 'ais': values}
    gtin = result['gtin']
    if gtin:
        if not re.fullmatch(r'\d{14}', gtin) or (sum(int(v)*(3 if i%2==0 else 1) for i,v in enumerate(gtin[:-1][::-1]))+int(gtin[-1]))%10:
            return {'error': 'GTIN non valido'}
    if '17' in values:
        try:
            s = values['17']
            if not re.fullmatch(r'\d{6}', s):
                raise ValueError()
            y,m,d = 2000+int(s[:2]),int(s[2:4]),int(s[4:])
            result['expiry'] = date(y,m,d or calendar.monthrange(y,m)[1]).isoformat()
        except ValueError:
            return {'error': 'Scadenza GS1 non valida'}
    return result


def decode_barcodes(image):
    import zxingcpp
    results = []
    # Retry conservative threshold/scale variants; retain every distinct payload.
    variants = [image]
    gray = image.convert('L')
    variants += [gray.point(lambda p: 255 if p > t else 0) for t in (80, 120, 160)]
    small = gray.resize((max(1, int(gray.width*.75)), max(1, int(gray.height*.75))))
    variants.append(small.point(lambda p: 255 if p > 80 else 0))
    seen = set()
    for variant in variants:
        for barcode in zxingcpp.read_barcodes(variant):
            raw = barcode.bytes.decode('utf-8', errors='replace')
            symbology = getattr(barcode, 'symbology_identifier', '')
            if raw in seen:
                continue
            if symbology in {']d2', ']C1'} or raw.startswith((']d2', ']C1', '(01)')):
                seen.add(raw)
                results.append({'raw': raw, 'format': str(barcode.format), **gs1_parse(raw)})
    return results


def reconcile(item, barcodes):
    row = dict(item)
    warnings = [row.get('warning')] if row.get('warning') else []
    row['barcodes'] = barcodes
    for barcode in barcodes:
        if barcode.get('error'):
            warnings.append(barcode['error'])
            continue
        # AI (01) identifies a GTIN, never a catalogue REF.
        if barcode.get('gtin'):
            row['gtin'] = barcode['gtin']
        for field in ('lot', 'expiry'):
            decoded = barcode.get(field)
            if decoded:
                if row.get(field) and str(row[field]).strip() != decoded:
                    warnings.append('Conflitto OCR/GS1: ' + field)
                elif not row.get(field):
                    row[field] = decoded
    code = str(row.get('code') or '').strip()
    if re.fullmatch(r'\d{14}', code) or code.startswith(('(01)', ']d2')):
        row['code'] = None
        warnings.append('GTIN/UDI letto al posto del REF')
    for field in ('code', 'lot', 'expiry'):
        if not row.get(field):
            warnings.append('Campo critico non letto: ' + field)
    row['quantity'] = 1  # One physical implanted-item label, not package quantity.
    row['warning'] = ' · '.join(dict.fromkeys(warnings)) or None
    row['reviewed'] = False
    return row


def aggregate_labels(rows):
    """Reviewed physical observations -> stock quantities, preserving expiry."""
    out, indexes, seen = [], {}, set()
    for original in rows:
        row = dict(original)
        label_id = row.get('label_id')
        if not label_id:
            raise ValueError('Etichetta senza identità fisica')
        if label_id in seen:
            raise ValueError('Etichetta fisica ripetuta: ' + label_id)
        seen.add(label_id)
        key = tuple(str(row.get(k) or '').strip() for k in ('codice','lotto','scadenza'))
        if key in indexes:
            out[indexes[key]]['quantita'] += row['quantita']
            out[indexes[key]]['label_ids'].append(label_id)
        else:
            row['label_ids'] = [label_id]
            indexes[key] = len(out)
            out.append(row)
    return out


def review_errors(rows, expected_ids, expected_count, count_verified):
    errors = []
    if not count_verified or expected_count != len(expected_ids):
        errors.append('Conteggio fisico non verificato o discordante')
    ids = [r.get('label_id') for r in rows]
    if set(ids) != set(expected_ids) or len(ids) != len(set(ids)):
        errors.append('Etichette mancanti, aggiunte o duplicate nella lista')
    for row in rows:
        if not row.get('verificata'):
            errors.append(str(row.get('label_id')) + ': verifica singola etichetta richiesta')
        if row.get('escludi_riga'):
            continue
        code = str(row.get('codice') or '').strip()
        if not code or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9. /-]*', code) or re.fullmatch(r'\d{14}', code) or '?' in code:
            errors.append('REF incompleto o non valido: ' + code)
        if not row.get('lotto') and not row.get('senza_lotto'):
            errors.append('Lotto obbligatorio: ' + code)
        if not row.get('senza_lotto'):
            try:
                date.fromisoformat(str(row.get('scadenza') or ''))
            except ValueError:
                errors.append('Scadenza non verificata: ' + code)
        try:
            qty = float(row.get('quantita'))
            if not math.isfinite(qty) or qty != 1:
                raise ValueError()
        except (TypeError, ValueError):
            errors.append('Una etichetta fisica deve rappresentare un pezzo: ' + code)
    return errors


def inventory_errors(rows, stock):
    normalize = lambda value: re.sub(r'[^A-Z0-9]', '', str(value or '').upper())
    errors = []
    for row in aggregate_labels(rows):
        code, lot, expiry = row['codice'], row['lotto'], row['scadenza']
        products = [s for s in stock if normalize(s.get('codice')) == normalize(code)]
        matches = [s for s in products if str(s.get('lotto') or '').strip() == lot]
        if not products:
            errors.append('Prodotto sconosciuto: ' + code)
        elif not matches:
            errors.append('Lotto non corrispondente: ' + code + ' / ' + lot)
        else:
            compatible = [s for s in matches if str(s.get('scadenza') or '') == expiry or row.get('senza_lotto')]
            if not compatible:
                errors.append('Scadenza magazzino diversa o non disponibile: ' + code + ' / ' + lot)
            elif sum(max(0, float(s.get('quantita') or 0)) for s in compatible) < row['quantita']:
                errors.append('Quantità insufficiente: ' + code + ' / ' + lot)
    return errors


def analyze_labels(path, client, model, item_schema, parse):
    """Two stages: locate geometry, then read exactly one crop per observation."""
    detector_schema = {'type':'object','properties':{
        'labels':{'type':'array','items':{'type':'object','properties':{
            'bbox':{'type':'array','items':{'type':'integer'},'minItems':4,'maxItems':4},
            'rotation':{'type':'integer','enum':[0,90,180,270]}},
            'required':['bbox','rotation'],'additionalProperties':False}},
        'warning':{'type':['string','null']}},'required':['labels','warning'],'additionalProperties':False}
    pages = render_pages(path)
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()[:20]
    items, warnings = [], []
    for number, page in enumerate(pages, 1):
        preview = page.copy()
        preview.thumbnail((2200,2200))
        located = parse(client.responses.create(model=model, store=False,
            input=[{'role':'user','content':[
                {'type':'input_text','text':'Individua OGNI etichetta fisica adesiva di prodotto ortopedico, inclusi bordi e etichette verticali. Non leggere i dati. Restituisci rettangoli stretti non sovrapposti in coordinate della immagine originale da 0 a 1000 [sinistra,alto,destra,basso]. Una etichetta per rettangolo, non una colonna. rotation è la rotazione antioraria necessaria a leggere quel singolo ritaglio. Non includere intestazione, firma, celle vuote. Segnala parti non localizzabili.'},
                {'type':'input_image','image_url':image_url(preview),'detail':'high'}]}],
            text={'format':{'type':'json_schema','name':'physical_labels','schema':detector_schema,'strict':True}}))
        if located.get('warning'):
            warnings.append(f'Pagina {number}: {located["warning"]}')
        regions = unique_regions([dict(r,page=number) for r in located['labels']])
        for index, region in enumerate(regions,1):
            label_id = f'{digest}:p{number}:l{index}'
            original = crop_region(page,region['bbox'])
            crop = original.rotate(region['rotation'],expand=True)
            try:
                decoded = decode_barcodes(crop)
                response = client.responses.create(model=model, store=False,
                    input=[{'role':'user','content':[
                        {'type':'input_text','text':'Trascrivi SOLO questa singola etichetta: REF stampato (mai GTIN/UDI), lotto, scadenza ISO, descrizione e produttore. Non dedurre dati da descrizioni o cataloghi. Per caratteri incerti usa null e warning. quantity=1. Non usare quantità della confezione. Se il ritaglio contiene più etichette o è troncato segnala warning. La confidence non sostituisce verifica manuale.'},
                        {'type':'input_image','image_url':image_url(crop),'detail':'high'}]}],
                    text={'format':{'type':'json_schema','name':'single_label','schema':item_schema,'strict':True}})
                row = reconcile(parse(response),decoded)
            except Exception as exc:
                # Preserve failed observations; never silently reduce label count.
                row = {key:None for key in item_schema['properties']}
                row.update(quantity=1, confidence=0, warning=f'Lettura fallita ({type(exc).__name__}): verificare manualmente',reviewed=False)
            row.update(label_id=label_id,page=number,bbox=region['bbox'],rotation=region['rotation'],crop_data_url=image_url(crop),source_document=digest)
            items.append(row)
    return {'document_type':'scarico_sala','items':items,'back_orders':[],
            'physical_label_count':len(items),'detection_warnings':warnings,
            'count_verified':False,'clinic_name':None,'clinical_record':None,'procedure_date':None,'surgeon':None,'confidence':0}
