"""Physical-label OCR: geometry precedes identity; no production writes."""
import base64
import calendar
import csv
import hashlib
import math
import re
import shutil
import subprocess
from datetime import date
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, ImageFilter

PIPELINE_VERSION = 'physical-label-v15-local-crops-gtin'


def local_ref_evidence(image):
    """Independent literal OCR. Never translate 5 to S or recover missing suffixes."""
    if not shutil.which('tesseract'):
        return {'status': 'unavailable', 'reads': [], 'candidates': []}
    reads, candidates = [], set()
    try:
        enlarged = image.resize(tuple(max(1, round(v * min(5.0, 1800 / max(image.size)))) for v in image.size), Image.Resampling.LANCZOS) if max(image.size) < 1800 else image.copy()
        for variant, psm in ((image, 6), (prepare_crop(image), 6), (enlarged, 11)):
            buffer = BytesIO()
            variant.save(buffer, format='PNG')
            result = subprocess.run(
                ['tesseract', 'stdin', 'stdout', '-l', 'eng', '--psm', str(psm), 'tsv'],
                input=buffer.getvalue(), capture_output=True, timeout=15, check=True)
            words = list(csv.DictReader(result.stdout.decode('utf-8', errors='replace').splitlines(),delimiter='\t',quoting=csv.QUOTE_NONE))
            reads.append(' '.join(w.get('text','') for w in words if w.get('text')))
            for word in words:
                token = (word.get('text') or '').strip()
                if re.fullmatch(r'(?:\d{2}\.\d{3}\.\d{3}|\d{3}\.\d{3})(?:TS|S)',token) and float(word.get('conf') or -1)>=80:
                    candidates.add(token)
    except (OSError, subprocess.SubprocessError):
        return {'status': 'unavailable', 'reads': reads, 'candidates': []}
    candidates = sorted(candidates)
    return {'status': 'read' if candidates else 'unreadable', 'reads': reads,
            'candidates': candidates}


def verify_ref_evidence(item, evidence):
    row = dict(item)
    row['ref_original'] = row.get('code')
    row['local_ref_evidence'] = evidence
    warnings = [row['warning']] if row.get('warning') else []
    code = str(row.get('code') or '').strip()
    if code and code == str(row.get('lot') or '').strip():
        row['code'] = None
        warnings.append('REF uguale al lotto: verificare i due campi separatamente')
    if code and row.get('is_sterile') is True and re.fullmatch(r'(?:\d{2}\.\d{3}\.\d{3}|\d{3}\.\d{3})5?', code):
        row['code'] = None
        warnings.append('REF sterile senza suffisso S/TS verificabile: non aggiungere automaticamente')
    candidates = evidence.get('candidates', [])
    # A split 04.211.016S may produce only 211.016S. This is incomplete
    # evidence, never a different identity and never a licence to add a prefix.
    partial = [c for c in candidates if code.endswith('.' + c)]
    candidates = [c for c in candidates if c not in partial]
    if partial:
        warnings.append('OCR locale con REF parziale: confronto manuale con il ritaglio richiesto')
    if code and candidates and candidates != [code]:
        row['code'] = None
        warnings.append('REF discordante o ambiguo tra OCR locale e AI')
    elif evidence.get('status') in {'unavailable', 'unreadable'}:
        warnings.append('REF non confermato da OCR locale: confronto manuale con il ritaglio richiesto')
    row['warning'] = ' · '.join(warnings) or None
    return row


def prepare_crop(image):
    """Bounded, non-generative enlargement; preserve original as evidence."""
    scale = min(3.0, 1800 / max(image.size))
    enlarged = image.resize(tuple(max(1, round(v * scale)) for v in image.size), Image.Resampling.LANCZOS) if scale > 1 else image.copy()
    return ImageOps.autocontrast(enlarged.convert('RGB'), cutoff=0).filter(
        ImageFilter.UnsharpMask(radius=1, percent=120, threshold=3))


def compare_reads(first, second):
    """Agreement is evidence only, never automatic stock authorization."""
    row = dict(first)
    warnings = [row['warning']] if row.get('warning') else []
    row['ocr_reads'] = [dict(first), dict(second)]
    for field in ('code', 'lot', 'expiry', 'gtin'):
        a, b = first.get(field), second.get(field)
        if not a or not b or str(a).strip() != str(b).strip():
            row[field] = None
            warnings.append('Letture indipendenti discordanti o incomplete: ' + field)
    row['warning'] = ' · '.join(warnings) or None
    return row


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
        page=ImageOps.exif_transpose(image).convert('RGB')
        page.info['_ocr_source_quantization']=getattr(image,'quantization',None)
        page.info['_ocr_source_exif']={str(k):image.getexif().get(k) for k in (305,40962,40963)}
        return [page]


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
        fixed = {'01':14,'17':6,'11':6,'15':6,'20':2}
        variable = {'10':20,'21':20,'30':8,'91':90,'92':90,'93':90}
        if ai not in fixed and ai not in variable:
            return {'error': 'AI GS1 non supportato: ' + ai}
        if ai in fixed and (len(value)!=fixed[ai] or not value.isdigit()):
            return {'error': 'Campo GS1 a lunghezza fissa non valido: ' + ai}
        if ai in variable and (not 1<=len(value)<=variable[ai] or any(ord(c)<32 for c in value)):
            return {'error': 'Campo GS1 variabile non valido: ' + ai}
        if ai=='30' and not value.isdigit():
            return {'error':'Quantità GS1 non valida'}
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
    from datamatrix_reader import decode
    return decode(image)


def reconcile(item, barcodes):
    row = dict(item)
    warnings = [row.get('warning')] if row.get('warning') else []
    row['barcodes'] = barcodes
    valid = [b for b in barcodes if not b.get('error')]
    if any(len({b.get(f) for b in valid if b.get(f)}) > 1 for f in ('gtin', 'lot', 'expiry')):
        row.update(code=None, lot=None, expiry=None, gtin=None)
        warnings.append('Più identità GS1 nel ritaglio: verificare i confini della singola etichetta')
        barcodes = []
    conflicted_fields = set()
    for barcode in barcodes:
        if barcode.get('error'):
            warnings.append(barcode['error'])
            continue
        # AI (01) identifies a GTIN, never a catalogue REF.
        for field in ('gtin', 'lot', 'expiry'):
            if field in conflicted_fields:
                continue
            decoded = barcode.get(field)
            if decoded:
                if row.get(field) and str(row[field]).strip() != decoded:
                    row[field + '_ocr_original'] = row[field]
                    row[field] = None
                    conflicted_fields.add(field)
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
    from ocr_review import verified_physical_count
    try:
        physical_count=verified_physical_count(rows)
    except ValueError as exc:
        errors.append(str(exc));physical_count=len(expected_ids)
    if not count_verified or expected_count != physical_count:
        errors.append('Conteggio fisico non verificato o discordante')
    ids = [r.get('label_id') for r in rows]
    if set(ids) != set(expected_ids) or len(ids) != len(set(ids)):
        errors.append('Etichette mancanti, aggiunte o duplicate nella lista')
    for row in rows:
        if not row.get('verificata'):
            errors.append(str(row.get('label_id')) + ': verifica singola etichetta richiesta')
        if row.get('escludi_riga') or row.get('duplicate_of'):
            continue
        if row.get('cross_photo_candidates') and not row.get('physical_distinct_confirmed'):
            errors.append('Identità fisica da risolvere tra più foto: ' + str(row.get('label_id')))
        code = str(row.get('codice') or '').strip()
        if not code or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9. /-]*', code) or re.fullmatch(r'\d{14}', code) or '?' in code:
            errors.append('REF incompleto o non valido: ' + code)
        if row.get('is_sterile') is True and re.fullmatch(r'(?:\d{2}\.\d{3}\.\d{3}|\d{3}\.\d{3})5?', code):
            errors.append('REF sterile senza suffisso verificato: ' + code)
        gtin = str(row.get('gtin') or '').strip()
        if gtin and gs1_parse('(01)'+gtin).get('error'):
            errors.append('GTIN non valido: ' + gtin)
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


def select_label_regions(local_regions, proposals, layout, page, source_page=None):
    """Synthes template geometry needs independent layout and count support.

    A DataMatrix on ATTUNE/SmartSet cannot license the Synthes crop offsets.
    Ambiguous or incomplete local grids use the complete visual proposals.
    """
    if (source_page is not None and layout == 'synthes_datamatrix'
            and len(local_regions) >= 3
            and all(r.get('geometry_source') == 'local_datamatrix_sticker' for r in local_regions)):
        out = [dict(r, page=page) for r in local_regions]
        for proposal in proposals:
            if any(overlap(r['bbox'], proposal['bbox']) >= .5 for r in out):
                continue
            # A proposal without a physical anchor must have independent product
            # evidence. Header fields must not become implanted-item quantities.
            crop = crop_region(source_page, proposal['bbox'])
            evidence = local_ref_evidence(crop)
            try:
                barcodes = decode_barcodes(crop)
            except Exception:
                barcodes = []
            if evidence.get('candidates') or any(not b.get('error') for b in barcodes):
                out.append(proposal)
        return unique_regions(out)
    if layout != 'synthes_datamatrix' or not local_regions or len(local_regions) != len(proposals):
        return proposals
    remaining = list(proposals)
    for local in local_regions:
        a = local['bbox']
        matches = []
        for index, proposal in enumerate(remaining):
            b = proposal['bbox']
            intersection = max(0,min(a[2],b[2])-max(a[0],b[0])) * max(0,min(a[3],b[3])-max(a[1],b[1]))
            area = max(1,(b[2]-b[0])*(b[3]-b[1]))
            if intersection/area >= .7:
                matches.append(index)
        if len(matches) != 1:
            return proposals
        remaining.pop(matches[0])
    return [dict(r,page=page) for r in local_regions]


def merge_linear_regions(local_regions, proposals, page):
    """Refine only unambiguous one-to-one matches; preserve unmatched labels.

    A barcode detector can miss a faint sticker or group two adjacent stickers.
    Neither case licenses replacing the complete visual proposal list.
    """
    local = unique_regions([dict(r, page=page) for r in local_regions])
    proposals = unique_regions(proposals)
    links = [[i for i, proposal in enumerate(proposals)
              if overlap(region['bbox'], proposal['bbox']) >= .5]
             for region in local]
    output = [dict(r) for r in proposals]
    for region, matches in zip(local, links):
        if len(matches) == 1 and sum(matches[0] in m for m in links) == 1:
            output[matches[0]] = region
        elif not matches and not any(overlap(region['bbox'], p['bbox']) > 0
                                     for p in proposals):
            output.append(region)
    return sorted(output, key=lambda r: (r['page'], r['bbox'][1], r['bbox'][0]))


def analyze_labels(path, client, model, item_schema, parse, *, privacy_approval=None):
    """Two stages: locate geometry, then read exactly one crop per observation."""
    from ocr_privacy import approved_regions
    approved=approved_regions(path,privacy_approval)
    pages = render_pages(path)
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()[:20]
    items, warnings, unconfirmed_regions, annotated_pages = [], [], [], []
    acquisition=[]
    for number, page in enumerate(pages, 1):
        preview = page.copy()
        preview.thumbnail((2200,2200))
        # Geometry is local and operator approved; never transmit a page or header.
        regions=[r for r in approved if r['page']==number]
        from image_quality import acquisition_report
        capture=acquisition_report(page,regions)
        acquisition.append(dict(capture,page=number))
        warnings.extend(capture['warnings'])
        from image_quality import geometry_alerts
        warnings.extend(f'Pagina {number}: {message}' for message in geometry_alerts(regions))
        from PIL import ImageDraw
        overview = preview.copy()
        pen = ImageDraw.Draw(overview)
        for index, region in enumerate(regions, 1):
            pixels = tuple(round(v * (overview.width if i%2==0 else overview.height)/1000)
                           for i,v in enumerate(region['bbox']))
            pen.rectangle(pixels, outline='red', width=3)
            pen.text(pixels[:2], str(index), fill='red')
        annotated_pages.append({'page':number, 'page_data_url':image_url(overview)})
        for index, region in enumerate(regions,1):
            label_id = f'{digest}:p{number}:l{index}'
            original = crop_region(page,region['bbox'])
            crop = original.rotate(region['rotation'] + region.get('deskew_angle', 0),
                                   resample=Image.Resampling.BICUBIC, expand=True, fillcolor='white')
            decoded = []
            try:
                try:
                    decoded = decode_barcodes(crop)
                except Exception:
                    decoded = []
                    warnings.append(f'{label_id}: decodifica DataMatrix non disponibile')
                response = client.responses.create(model=model, store=False,
                    input=[{'role':'user','content':[
                        {'type':'input_text','text':'Trascrivi SOLO questa singola etichetta: REF stampato (mai GTIN/UDI), GTIN stampato dopo (01) in un campo separato, lotto, scadenza ISO, descrizione e produttore. Non dedurre dati da descrizioni o cataloghi. Per caratteri incerti usa null e warning. quantity=1. Non usare quantità della confezione. Se il ritaglio contiene più etichette o è troncato segnala warning. Ignora eventuali adesivi interni ospedalieri con soli codici numerici e (1/1), senza REF/LOT e dati del produttore. La confidence non sostituisce verifica manuale.'},
                        {'type':'input_image','image_url':image_url(crop),'detail':'high'}]}],
                    text={'format':{'type':'json_schema','name':'single_label','schema':item_schema,'strict':True}})
                first = parse(response)
                if not decoded:
                    first['warning']=' · '.join(filter(None,[first.get('warning'),'DataMatrix non decodificato: acquisire una nuova foto più ravvicinata; ripiego sul testo stampato']))
                second = parse(client.responses.create(model=model, store=False,
                    input=[{'role':'user','content':[
                        {'type':'input_text','text':'Leggi questa sola etichetta da zero. Trascrivi il REF stampato completo di punti, zeri iniziali e suffissi S/TS, lotto, scadenza ISO e GTIN stampato dopo (01), separato dal REF. Non ricostruire caratteri da descrizioni, GTIN o cataloghi. Campi incerti a null. Non confondere 018, 020, 016, 085, 005. quantity=1.'},
                        {'type':'input_image','image_url':image_url(prepare_crop(crop)),'detail':'high'}]}],
                    text={'format':{'type':'json_schema','name':'independent_label_read','schema':item_schema,'strict':True}}))
                row = verify_ref_evidence(reconcile(compare_reads(first, second),decoded),
                                          local_ref_evidence(crop))
            except Exception as exc:
                # Preserve failed observations; never silently reduce label count.
                row = {key:None for key in item_schema['properties']}
                row.update(quantity=1, confidence=0, warning=f'Lettura fallita ({type(exc).__name__}): verificare manualmente',reviewed=False)
                row = reconcile(row, decoded)
            row.update(label_id=label_id,page=number,bbox=region['bbox'],rotation=region['rotation'],crop_data_url=image_url(crop),source_document=digest,
                       geometry_source=region.get('geometry_source','ai_proposal'),finder_bbox=region.get('finder_bbox'),
                       deskew_angle=region.get('deskew_angle', 0))
            from image_quality import inspect_quality
            row['image_quality']=inspect_quality(crop)
            from ocr_review import assess_label
            row['assessment'] = assess_label(row)
            items.append(row)
    metadata = {k: None for k in ('clinic_name', 'clinical_record', 'procedure_date', 'surgeon')}
    warnings.append('Privacy: intestazione non inviata al modello; compilare manualmente i dati intervento')
    return {'document_type':'scarico_sala','items':items,'back_orders':[],
            'pipeline_version':PIPELINE_VERSION,
            'physical_label_count':len(items),'detection_warnings':warnings,'acquisition':acquisition,
            'unconfirmed_regions':unconfirmed_regions,'annotated_pages':annotated_pages,
            'count_verified':False, **metadata, 'confidence':0}
