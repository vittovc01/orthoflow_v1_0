"""Transport-neutral multi-document API; usable from Streamlit/FastAPI workers.

Upload byte validation and extraction never persist anything in Supabase.
The caller must authenticate, throttle requests and keep review state isolated.
"""
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from ocr_repository import OriginalDocument
from ocr_review import build_review, mark_cross_photo_candidates


def analyze_documents(documents, *, analyzer, catalog=None, soon_days=90):
    if not 1<=len(documents)<=20 or sum(len(d.content) for d in documents)>50*1024*1024:
        raise ValueError('Caricare da 1 a 20 documenti, massimo 50 MiB totali')
    result = {'items':[],'annotated_pages':[],'detection_warnings':[],
              'unconfirmed_regions':[],'documents':[],'review_required':True}
    seen_documents={}
    with TemporaryDirectory(prefix='orthoflow-review-') as tmp:
        for index, document in enumerate(documents):
            mime, extension = document.validate()
            digest=hashlib.sha256(document.content).hexdigest()
            if digest in seen_documents:
                result['documents'].append({'index':index,'name':document.name,'status':'duplicate',
                                            'duplicate_of':seen_documents[digest]})
                result['detection_warnings'].append(f'Documento {index+1}: copia identica di una foto già analizzata; non ricontata')
                continue
            seen_documents[digest]=index
            path = Path(tmp)/f'{index:02}{extension}'
            path.write_bytes(document.content)
            try:
                incoming = analyzer(str(path),mode='scarico_sala')
            except Exception as exc:
                result['detection_warnings'].append(f'Documento {index+1}: analisi non completata ({type(exc).__name__}); riprovare o acquisire una nuova foto')
                result['documents'].append({'index':index,'name':document.name,'status':'failed'})
                continue
            result['documents'].append({'index':index,'name':document.name,'status':'analyzed'})
            for key in ('items','annotated_pages','detection_warnings','unconfirmed_regions'):
                entries = incoming.get(key) or []
                if key in ('items','annotated_pages','unconfirmed_regions'):
                    entries = [dict(entry,document_index=index) for entry in entries]
                result[key].extend(entries)
            result['pipeline_version'] = incoming.get('pipeline_version')
            for key in ('clinic_name','clinical_record','procedure_date','surgeon'):
                if not result.get(key) and incoming.get(key):
                    result[key] = incoming[key]
    mark_cross_photo_candidates(result['items'])
    return build_review(result,catalog=catalog,soon_days=soon_days)
