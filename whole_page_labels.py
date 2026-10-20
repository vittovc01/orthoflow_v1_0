"""Read products in page context. Geometry is evidence, never an OCR input gate.

The user-facing upload notice discloses whole-page transmission. Source pages
are not copied into extraction results or the product-only OCR archive.
"""
import hashlib
import math
from collections import Counter
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from ai_failures import failure_kind, provider_notice, request_with_backoff

from label_pipeline import (PIPELINE_VERSION, iter_pages as render_pages, image_url, compare_reads,
                            crop_region, decode_barcodes, reconcile, verify_ref_evidence)


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


class WholePageReadError(RuntimeError):
    def __init__(self, page, failures, kind=None):
        self.kind = kind
        self.public_reason = f'Pagina {page}: ' + '; '.join(failures)
        super().__init__(self.public_reason)


def failure_reason(exc):
    kind = failure_kind(exc)
    if kind:
        return provider_notice(kind)
    reason = type(exc).__name__
    status = getattr(exc, 'status_code', None)
    if isinstance(status, int):
        reason += f' HTTP {status}'
    # Schema diagnostics contain only our schema, never image/provider payloads,
    # credentials or clinical text. Other provider messages are not exposed.
    if getattr(exc, 'code', None) == 'invalid_json_schema':
        reason += ': ' + str(getattr(exc, 'message', 'Schema non valido'))[:700]
    return reason


def vision_options(model):
    if model in {'gpt-6-astra','gpt-5.4'}:
        return 'original', {'reasoning':{'effort':'low'}}
    return 'high', {}


def prepare_page(page, patch_budget=28000):
    """Keep the whole page; bound original-detail requests below API limits."""
    patches = lambda image: math.ceil(image.width/32)*math.ceil(image.height/32)
    scale = min(1,65535/max(page.size),math.sqrt(patch_budget/patches(page)))
    if scale < 1:
        page = page.resize(tuple(max(1,math.floor(v*scale*.99)) for v in page.size))
    while patches(page) > patch_budget:
        page = page.resize(tuple(max(1,math.floor(v*.99)) for v in page.size))
    return page


def iou(a, b):
    intersection = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    areas = [(r[2]-r[0])*(r[3]-r[1]) for r in (a, b)]
    return intersection / (sum(areas)-intersection) if intersection else 0


def spatial_score(a, b):
    # Full-page models may outline different portions of the same partly
    # covered/vertical sticker. Its physical centre remains a useful anchor.
    distance = math.hypot((a[0]+a[2]-b[0]-b[2])/2, (a[1]+a[3]-b[1]-b[3])/2)
    diagonal = (math.hypot(a[2]-a[0],a[3]-a[1]) + math.hypot(b[2]-b[0],b[3]-b[1]))/2
    proximity = .5 * max(0, 1-distance/max(1,diagonal))
    return max(iou(a,b), proximity)


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
    def identity(row):
        return tuple(str(row.get(k) or '').strip() for k in ('code','lot','expiry'))
    # When both complete transcriptions agree on the entire product multiset,
    # bounding-box disagreement must not increase the physical quantity. Match
    # occurrences one to one, retaining every occurrence in each pass (including
    # two, three, ... identical stickers); this is not deduplication by identity.
    keys_a, keys_b = [identity(r) for r in first], [identity(r) for r in second]
    duplicate_positions = any(iou(rows[i]['bbox'], rows[j]['bbox']) > .85
        for rows in (first,second) for i in range(len(rows)) for j in range(i))
    if (first and all(all(key) for key in keys_a+keys_b) and
            Counter(keys_a) == Counter(keys_b) and not duplicate_positions):
        available = set(range(len(second)))
        result = []
        for a,key in zip(first,keys_a):
            j = max((j for j in available if keys_b[j] == key),
                    key=lambda j:spatial_score(a['bbox'],second[j]['bbox']))
            available.remove(j)
            result.append(compare_reads(a,second[j]))
        return result
    edges = sorted(((spatial_score(a['bbox'], b['bbox']), i, j) for i, a in enumerate(first)
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
            chosen = spatial_score(a['bbox'], b['bbox'])
            ambiguous = (any(iou(a['bbox'], x['bbox']) > .85 for k,x in enumerate(first) if k != i) or
                         any(iou(b['bbox'], x['bbox']) > .85 for k,x in enumerate(second) if k != matched[i]) or
                         any(spatial_score(a['bbox'], x['bbox']) >= chosen-.05
                             for k,x in enumerate(second) if k != matched[i]) or
                         any(spatial_score(b['bbox'], x['bbox']) >= chosen-.05
                             for k,x in enumerate(first) if k != i))
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


def optional_product_regions(page):
    try:
        from region_privacy import safe_product_regions
        return safe_product_regions(page)[0], False
    except Exception:
        return [], True


def analyze_labels(path, client, model, item_schema, parse):
    # Only local evidence runs in parallel. API reads remain sequential, with
    # the same model, pixels, prompts, consensus and rate-limit handling.
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix='product-evidence') as executor:
        return _analyze_labels(path, client, model, item_schema, parse, executor)


def _analyze_labels(path, client, model, item_schema, parse, executor):
    schema = {'type':'object','properties':{
        'labels':{'type':'array','items':{'type':'object','properties':{
            'bbox':{'type':'array','items':{'type':'integer'},'minItems':4,'maxItems':4},
            'rotation':{'type':'integer','enum':[0,90,180,270]},'item':item_schema},
            'required':['bbox','rotation','item'],'additionalProperties':False}},
        'warning':{'type':['string','null']}},'required':['labels','warning'],'additionalProperties':False}
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()[:20]
    items, warnings = [], []
    active_model = model
    for number, page in enumerate(render_pages(path), 1):
        read_page = prepare_page(page)
        page_url = image_url(read_page)
        evidence = None
        reads = []
        failures = []
        for attempt in range(2):
            try:
                def request():
                    detail, options = vision_options(active_model)
                    return client.responses.create(model=active_model, store=False,
                        input=[{'role':'user','content':[
                            {'type':'input_text','text':PROMPT + ('\nSeconda lettura indipendente: riconta tutti gli adesivi da zero.' if attempt else '')},
                            {'type':'input_image','image_url':page_url,'detail':detail}]}],
                        text={'format':{'type':'json_schema','name':'whole_page_product_labels','schema':schema,'strict':True}}, **options)
                try:
                    raw_response = request_with_backoff(request)
                except Exception as exc:
                    if active_model != 'gpt-6-astra' or getattr(exc,'status_code',None) != 404:
                        raise
                    active_model = 'gpt-5.4'
                    warnings.append('Modello gpt-6-astra non disponibile per questo account: lettura eseguita con gpt-5.4 a risoluzione originale')
                    raw_response = request_with_backoff(request)
                response = parse(raw_response)
                reads.append(observations(response))
                if evidence is None:
                    evidence = executor.submit(optional_product_regions, page)
                if response.get('warning'):
                    warnings.append(f'Pagina {number}: {response["warning"]}')
            except Exception as exc:
                reads.append(None)
                failures.append(failure_reason(exc))
                kind = failure_kind(exc)
                if kind:
                    if not any(r is not None for r in reads):
                        raise WholePageReadError(number, [provider_notice(kind)], kind=kind) from None
                    warnings.append(provider_notice(kind))
                    break
                warnings.append(f'Pagina {number}: lettura {attempt+1} non completata ({type(exc).__name__}); verificare il conteggio sul foglio')
        while len(reads) < 2:
            reads.append(None)
        if reads == [None, None]:
            raise WholePageReadError(number, ['entrambe le letture fallite', *failures])
        rows = merge_reads(reads[0] or [], reads[1] or [])
        warnings.append(f'Pagina {number}: prima lettura {len(reads[0] or [])}, seconda lettura {len(reads[1] or [])}, etichette da verificare {len(rows)}')
        if not rows:
            warnings.append(f'Pagina {number}: nessuna etichetta letta; aggiungere le righe mancanti o riprovare')
        if reads[0] is None or reads[1] is None or len(reads[0]) != len(reads[1]):
            warnings.append(f'Pagina {number}: conteggio non concorde tra le due letture; confrontare tutte le etichette fisiche')
        # Evidence can overlap the second read but never gates the AI input.
        safe, evidence_failed = evidence.result() if evidence else ([], False)
        if evidence_failed:
            warnings.append(f'Pagina {number}: riscontri fotografici non disponibili; lettura della foto intera conservata')
        for index, row in enumerate(rows, 1):
            row.update(label_id=f'{digest}:p{number}:l{index}', page=number, source_document=digest,
                       geometry_source='whole_page_read', crop_data_url=None, ocr_model=active_model)
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
            # Keep literal identity checks from the previous reader, without
            # requiring a crop or rebuilding a missing sterile REF suffix.
            row = verify_ref_evidence(row, {'status':'whole_page','reads':[], 'candidates':[]})
            from ocr_review import assess_label
            row['assessment'] = assess_label(row)
            items.append(row)
    return {'document_type':'scarico_sala','items':items,'back_orders':[],
            'pipeline_version':PIPELINE_VERSION,'physical_label_count':len(items),
            'ocr_model':active_model,
            'detection_warnings':warnings,'unconfirmed_regions':[], 'annotated_pages':[],
            'count_verified':False,'clinic_name':None,'clinical_record':None,
            'procedure_date':None,'surgeon':None,'confidence':0}
