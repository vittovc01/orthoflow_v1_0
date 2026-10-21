"""Transport-neutral multi-document API; usable from Streamlit/FastAPI workers.

Upload byte validation and extraction never persist anything in Supabase.
The caller must authenticate, throttle requests and keep review state isolated.
"""
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from ocr_repository import OriginalDocument
from ocr_review import build_review


def document_fingerprint(path):
    # Do not retain a rasterised copy of the whole PDF during the AI analysis.
    from label_pipeline import iter_pages
    fingerprint = []
    for page in iter_pages(path):
        try:
            fingerprint.append((page.size, sha256(page.tobytes()).hexdigest()))
        finally:
            page.close()
    return tuple(fingerprint)


def analyze_documents(documents, *, analyzer, catalog=None, soon_days=90):
    if not 1<=len(documents)<=20 or sum(len(d.content) for d in documents)>50*1024*1024:
        raise ValueError('Caricare da 1 a 20 documenti, massimo 50 MiB totali')
    result = {'items':[],'annotated_pages':[],'detection_warnings':[],
              'unconfirmed_regions':[],'documents':[],'review_required':True}
    seen_documents = {}
    provider_block = None
    with TemporaryDirectory(prefix='orthoflow-review-') as tmp:
        for index, document in enumerate(documents):
            started = perf_counter()
            mime, extension = document.validate()
            path = Path(tmp)/f'{index:02}{extension}'
            path.write_bytes(document.content)
            try:
                if provider_block:
                    from whole_page_labels import WholePageReadError
                    raise WholePageReadError(1, [provider_block[1]], kind=provider_block[0])
                fingerprint = document_fingerprint(path)
                if fingerprint in seen_documents:
                    result['documents'].append({'index':index,'name':document.name,'status':'duplicate',
                                                'duplicate_of':seen_documents[fingerprint]})
                    result['detection_warnings'].append(f'Documento {index+1}: immagine già analizzata, non conteggiata due volte')
                    continue
                incoming = analyzer(str(path),mode='scarico_sala')
                seen_documents[fingerprint] = index
                if incoming.get('provider_failure_kind') in ('quota', 'rate_limit'):
                    from ai_failures import provider_notice
                    kind = incoming['provider_failure_kind']
                    provider_block = (kind, provider_notice(kind))
            except Exception as exc:
                from whole_page_labels import WholePageReadError
                reason = exc.public_reason if isinstance(exc, WholePageReadError) else type(exc).__name__
                kind = getattr(exc, 'kind', None)
                if kind in ('quota', 'rate_limit'):
                    provider_block = (kind, reason)
                result['detection_warnings'].append(f'Documento {index+1}: analisi non completata ({reason})')
                result['documents'].append({'index':index,'name':document.name,'status':'failed','failure_kind':kind})
                continue
            result['documents'].append({'index':index,'name':document.name,'status':'analyzed',
                                        'model':incoming.get('ocr_model'),
                                        'duration_seconds':round(perf_counter()-started, 2)})
            for key in ('items','annotated_pages','detection_warnings','unconfirmed_regions'):
                entries = incoming.get(key) or []
                if key in ('items','annotated_pages','unconfirmed_regions'):
                    entries = [dict(entry,document_index=index) for entry in entries]
                result[key].extend(entries)
            result['pipeline_version'] = incoming.get('pipeline_version')
            for key in ('clinic_name','clinical_record','procedure_date','surgeon'):
                if not result.get(key) and incoming.get(key):
                    result[key] = incoming[key]
    return build_review(result,catalog=catalog,soon_days=soon_days)
