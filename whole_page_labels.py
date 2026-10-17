"""Read products in page context. Geometry is evidence, never an OCR input gate.

The user-facing upload notice discloses whole-page transmission. Source pages
are not copied into extraction results or the product-only OCR archive.
"""
import hashlib
import math
from pathlib import Path

from label_pipeline import (PIPELINE_VERSION, render_pages, image_url, compare_reads,
                            crop_region, decode_barcodes, reconcile)


PROMPT = """Leggi visivamente TUTTA la foto del foglio, prima di considerare i ritagli.
Trascrivi OGNI etichetta fisica originale di prodotto ortopedico: REF stampato
completo di punti/trattini e suffissi S/TS, lotto e scadenza ISO YYYY-MM-DD.
Esamina ogni colonna, bordo, etichetta verticale, inclinata o parzialmente coperta.
Due adesivi fisici con identici REF e lotto sono DUE osservazioni, ognuna quantity=1.
Non contare due volte barcode o righe dello stesso adesivo. Non contare intestazioni,
firme, campi vuoti o adesivi interni di inventario. Non trascrivere nomi paziente,
cartelle cliniche, date intervento o altro testo clinico in nessun campo.
Non dedurre identificativi da descrizione o catalogo. GTIN è opzionale, distinto dal REF.
Non ricostruire caratteri nascosti: usa null e warning se il campo non è leggibile.
La posizione serve solo a collegare l'osservazione alla foto: bbox normalizzato
[sinistra,alto,destra,basso] 0..1000, una posizione per singolo adesivo.
Non raggruppare per REF/lotto. Riporta anche le etichette parzialmente illeggibili.
source_text deve contenere soltanto REF, lotto e scadenza del prodotto.
"""


def iou(a, b):
    intersection = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    areas = [(r[2]-r[0])*(r[3]-r[1]) for r in (a, b)]
    return intersection / (sum(areas)-intersection) if intersection else 0


def observations(result):
    """Reject malformed geometry explicitly, without silently deleting products."""
    rows = result.get('labels')
    if not isinstance(rows, list):
        raise ValueError('Risposta senza elenco etichette')
    out = []
    for entry in rows:
        box = entry.get('bbox', [])
        valid = (len(box) == 4 and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                 and math.isfinite(v) for v in box))
        if not valid or not (0 <= box[0] < box[2] <= 1000 and 0 <= box[1] < box[3] <= 1000):
            raise ValueError('Posizione etichetta non valida: rianalizzare la pagina')
        row = dict(entry['item'], bbox=list(box), rotation=entry['rotation'])
        row['quantity'] = 1
        # Do not retain unstructured page text in product audit records.
        row['source_text'] = ' | '.join(str(row.get(k) or '') for k in ('code','lot','expiry'))
        out.append(row)
    return out


def merge_reads(first, second):
    """One-to-one spatial consensus; product identity NEVER deduplicates labels."""
    edges = sorted(((iou(a['bbox'], b['bbox']), i, j) for i, a in enumerate(first)
                    for j, b in enumerate(second)), reverse=True)
    matched, used = {}, set()
    for score, i, j in edges:
        if score < .35:
            break
        if i not in matched and j not in used:
            matched[i] = j
            used.add(j)
    result = []
    for i, a in enumerate(first):
        if i in matched:
            b = second[matched[i]]
            row = compare_reads(a, b)
            # Competing spatial matches cannot establish a reliable identity.
            ambiguous = (sum(iou(a['bbox'], x['bbox']) >= .35 for x in second) != 1 or
                         sum(iou(b['bbox'], x['bbox']) >= .35 for x in first) != 1)
            if ambiguous:
                for field in ('code','lot','expiry'):
                    row[field] = None
                row['warning'] = 'Posizioni ambigue tra le due letture: verificare questa etichetta'
        else:
            row = dict(a, ocr_reads=[dict(a)], warning='Etichetta presente solo nella prima lettura: verificare sul foglio')
        result.append(row)
    for j, b in enumerate(second):
        if j not in used:
            result.append(dict(b, ocr_reads=[dict(b)], warning='Etichetta presente solo nella seconda lettura: verificare sul foglio'))
    return result


def analyze_labels(path, client, model, item_schema, parse):
    schema = {'type':'object','properties':{
        'labels':{'type':'array','items':{'type':'object','properties':{
            'bbox':{'type':'array','items':{'type':'integer'},'minItems':4,'maxItems':4},
            'rotation':{'type':'integer','enum':[0,90,180,270]},'item':item_schema},
            'required':['bbox','rotation','item'],'additionalProperties':False}},
        'warning':{'type':['string','null']}},'required':['labels','warning'],'additionalProperties':False}
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()[:20]
    items, warnings = [], []
    for number, page in enumerate(render_pages(path), 1):
        reads = []
        for attempt in range(2):
            try:
                response = parse(client.responses.create(model=model, store=False,
                    input=[{'role':'user','content':[
                        {'type':'input_text','text':PROMPT + ('\nSeconda lettura indipendente: riconta tutti gli adesivi da zero.' if attempt else '')},
                        {'type':'input_image','image_url':image_url(page),'detail':'high'}]}],
                    text={'format':{'type':'json_schema','name':'whole_page_product_labels','schema':schema,'strict':True}}))
                reads.append(observations(response))
                if response.get('warning'):
                    warnings.append(f'Pagina {number}: {response["warning"]}')
            except Exception as exc:
                reads.append(None)
                warnings.append(f'Pagina {number}: lettura {attempt+1} non completata ({type(exc).__name__}); verificare il conteggio sul foglio')
        if reads == [None, None]:
            raise RuntimeError(f'Pagina {number}: entrambe le letture fallite; riprovare, nessuno scarico creato')
        rows = merge_reads(reads[0] or [], reads[1] or [])
        if not rows:
            warnings.append(f'Pagina {number}: nessuna etichetta letta; aggiungere le righe mancanti o riprovare')
        if reads[0] is None or reads[1] is None or len(reads[0]) != len(reads[1]):
            warnings.append(f'Pagina {number}: conteggio non concorde tra le due letture; confrontare tutte le etichette fisiche')
        # Local crops are optional evidence AFTER both full-page reads. A failed
        # detector cannot suppress any observation or erase its transcription.
        try:
            from region_privacy import safe_product_regions
            safe, _ = safe_product_regions(page)
        except Exception:
            safe = []
            warnings.append(f'Pagina {number}: riscontri fotografici non disponibili; lettura della foto intera conservata')
        for index, row in enumerate(rows, 1):
            row.update(label_id=f'{digest}:p{number}:l{index}', page=number, source_document=digest,
                       geometry_source='whole_page_read', crop_data_url=None)
            # Only near-identical independently validated product rectangles can
            # supply archived pixels. Never crop an arbitrary AI proposal.
            matches = [r for r in safe if iou(r['bbox'], row['bbox']) >= .85]
            if len(matches) == 1:
                crop = crop_region(page, matches[0]['bbox'])
                try:
                    row = reconcile(row, decode_barcodes(crop))
                except Exception:
                    pass
                row['crop_data_url'] = image_url(crop)
            from ocr_review import assess_label
            row['assessment'] = assess_label(row)
            items.append(row)
    return {'document_type':'scarico_sala','items':items,'back_orders':[],
            'pipeline_version':PIPELINE_VERSION,'physical_label_count':len(items),
            'detection_warnings':warnings,'unconfirmed_regions':[], 'annotated_pages':[],
            'count_verified':False,'clinic_name':None,'clinical_record':None,
            'procedure_date':None,'surgeon':None,'confidence':0}
