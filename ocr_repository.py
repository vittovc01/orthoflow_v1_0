"""Server-only immutable OCR review archive. No stock movements are created here.

The authenticated application supplies actor; never take it from a mobile body.
No writes occur before explicit confirmation. Storage and Postgres are separate
services: ambiguous failures retain evidence for a safe retry with the same UUID.
"""
import hashlib
import base64
import json
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import UUID

from PIL import Image
from ocr_review import canonical_item, validate_confirmation

BUCKET = 'scarico-ocr-originals'
TABLE = 'ocr_review_sessions'


@dataclass(frozen=True)
class OriginalDocument:
    name: str
    content: bytes

    def validate(self):
        if not self.content or len(self.content)>25*1024*1024:
            raise ValueError('Documento vuoto o maggiore di 25 MiB')
        if self.content.startswith(b'%PDF-'):
            return 'application/pdf', '.pdf'
        with Image.open(BytesIO(self.content)) as image:
            if image.format not in {'JPEG','PNG','WEBP'}:
                raise ValueError('Formato immagine non supportato')
            kind = image.format
            image.verify()
        return {'JPEG':('image/jpeg','.jpg'),'PNG':('image/png','.png'),
                'WEBP':('image/webp','.webp')}[kind]


def without_images(value):
    """Raw photographs live only in private Storage, never duplicated as JSON URLs."""
    if isinstance(value,dict):
        return {k:without_images(v) for k,v in value.items()
                if k not in {'crop_data_url','page_data_url','image_url','annotated_pages'}}
    if isinstance(value,list):
        return [without_images(v) for v in value]
    if isinstance(value,float) and not math.isfinite(value):
        return None
    if isinstance(value,(datetime,)):
        return value.isoformat()
    if hasattr(value,'item'):
        return without_images(value.item())
    return value


def confirmed_evidence(extraction, confirmed):
    originals = {r['label_id']:canonical_item(r) for r in extraction['items']}
    output = []
    for row in confirmed:
        item = canonical_item(row)
        original = originals[item['label_id']]
        methods = {}
        for name in ('code','lot','expiry','description','gtin'):
            changed = item.get(name)!=original.get(name)
            methods[name] = 'manual' if changed or original.get('manual_entry') else original.get('assessment',{}).get('fields',{}).get(name,{}).get('method','ocr')
        output.append({**item,'confirmed_methods':methods})
    return without_images(output)


class SupabaseReviewRepository:
    def __init__(self, client):
        self.client = client

    def _existing(self, request_id):
        rows = self.client.table(TABLE).select('*').eq('id',request_id).limit(1).execute().data or []
        return rows[0] if rows else None

    def save_product_review(self, *, original_rows, correction_log, **kwargs):
        """Archive only immutable server-produced product crops and product fields.

        Never read the uploaded source file, its name, clinical metadata or discarded
        regions. Manual additions have no photograph; deleted labels remain in audit.
        """
        from label_pipeline import PIPELINE_VERSION
        extraction = kwargs['extraction']
        if extraction.get('pipeline_version') != PIPELINE_VERSION:
            raise ValueError('Rianalizza il documento con la versione privacy aggiornata')
        originals = {r['label_id']: r for r in original_rows}
        fields = {'label_id','code','lot','expiry','description','gtin','quantity','quantita',
                  'manual_entry','manual_fields','escludi_riga','verificata','reviewed','senza_lotto','is_sterile',
                  'page','bbox','rotation','source_document'}
        def product(row):
            return {k:v for k,v in canonical_item(row).items() if k in fields}
        confirmed = kwargs['confirmed']
        baseline = []
        for row in confirmed:
            original = originals.get(row['label_id'])
            if original is None and not row.get('manual_entry'):
                raise ValueError('Etichetta priva di estrazione originale immutabile')
            baseline.append(product(original if original is not None else row))
        documents = []
        for index, original in enumerate(original_rows):
            crop = original.get('crop_data_url')
            if not crop:
                continue
            if not crop.startswith(('data:image/png;base64,','data:image/jpeg;base64,')):
                raise ValueError('Ritaglio prodotto non valido')
            # Decode locally; no URL fetches or source-file reads are allowed.
            content = base64.b64decode(crop.split(',',1)[1],validate=True)
            # Re-encode to strip EXIF/comments and any trailing source bytes.
            with Image.open(BytesIO(content)) as image:
                image.load()
                clean = BytesIO()
                image.convert('RGB').save(clean,format='PNG')
            documents.append(OriginalDocument(f'etichetta-{index+1}.png',clean.getvalue()))
        logs = [{k:v for k,v in entry.items() if k in
                 {'label_id','operation','field','original','corrected','method','user','timestamp'}}
                for entry in correction_log]
        kwargs.update(extraction={'pipeline_version':PIPELINE_VERSION,'items':baseline,
                      'original_items':[product(r) for r in original_rows],
                      'correction_log':logs,'archive_scope':'product_labels_only'},
                      confirmed=[product(r) for r in confirmed], documents=documents,
                      product_crops=True)
        return self.save_confirmed(**kwargs)

    def save_confirmed(self, *, request_id, actor, extraction, confirmed, documents,
                       physical_count, count_verified, explicitly_confirmed=False, duplicates_reviewed=False,
                       product_crops=False):
        if explicitly_confirmed is not True:
            raise ValueError('Conferma esplicita richiesta: nessun salvataggio automatico')
        request_id = str(UUID(str(request_id)))
        aggregate = validate_confirmation(extraction,confirmed,physical_count=physical_count,
                                          count_verified=count_verified,actor=actor,duplicates_reviewed=duplicates_reviewed)
        if not (0 if product_crops else 1)<=len(documents)<=(200 if product_crops else 20):
            raise ValueError('Servono da 1 a 20 documenti originali')
        manifest, uploads = [], []
        for index, doc in enumerate(documents):
            mime, extension = doc.validate()
            digest = hashlib.sha256(doc.content).hexdigest()
            path = f'{request_id}/{index:02}-{digest}{extension}'
            manifest.append({'name':Path(doc.name).name,'sha256':digest,'bucket':BUCKET,
                             'path':path,'content_type':mime,'size':len(doc.content)})
            uploads.append((path,doc.content,mime))
        digests={d['sha256'] for d in manifest} | {d['sha256'][:20] for d in manifest}
        if not product_crops and any(r.get('source_document') and r['source_document'] not in digests for r in extraction.get('items',[])):
            raise ValueError('Documento originale diverso dalla fonte delle etichette')
        payload = {'actor':str(actor),'documents':manifest,'extracted':without_images(extraction),
                   'confirmed':confirmed_evidence(extraction,confirmed),'aggregate_rows':aggregate,
                   'physical_count':physical_count,'count_verified':True,
                   'pipeline_version':extraction.get('pipeline_version','unknown')}
        # Reject NaN/non-JSON values before making any external write.
        encoded = json.dumps(payload,sort_keys=True,ensure_ascii=False,allow_nan=False)
        fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
        existing = self._existing(request_id)
        if existing:
            if existing.get('payload_sha256')!=fingerprint or existing.get('actor')!=str(actor):
                raise ValueError('ID revisione già usato per dati diversi')
            return existing
        def upload_one(entry):
            path, content, mime = entry
            storage = self.client.storage.from_(BUCKET)
            try:
                storage.upload(path,content,file_options={'content-type':mime,'upsert':'false'})
            except Exception as exc:
                # A previous attempt can have uploaded this exact immutable object.
                # Never overwrite an existing photograph or discard ambiguous evidence.
                try:
                    previous = storage.download(path)
                except Exception:
                    raise RuntimeError('Archivio foto non completato; riprovare con lo stesso ID revisione') from exc
                if hashlib.sha256(previous).digest()!=hashlib.sha256(content).digest():
                    raise RuntimeError('Foto archivio discordante: verifica amministrativa richiesta') from exc
        # Bounded I/O overlap only; every immutable crop must be confirmed before
        # inserting the review or allowing the stock transaction to proceed.
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix='review-crop') as executor:
            list(executor.map(upload_one, uploads))
        record = {'id':request_id, **payload,'payload_sha256':fingerprint,
                  'confirmed_at':datetime.now(timezone.utc).isoformat()}
        try:
            response = self.client.table(TABLE).insert(record).execute()
            return (response.data or [record])[0]
        except Exception as exc:
            # An HTTP timeout may occur AFTER the transaction committed. Query first.
            try:
                existing = self._existing(request_id)
            except Exception:
                existing = None
            if existing and existing.get('payload_sha256')==fingerprint and existing.get('actor')==str(actor):
                return existing
            raise RuntimeError('Conferma archivio non verificabile; non ripetere lo scarico. Riprova archiviazione con lo stesso ID') from exc


def load_catalog_codes(client, table='codici_prodotto_scan', column='codice_articolo'):
    """Optional exact-code membership check. A scan registry may be incomplete."""
    import re
    if not re.fullmatch(r'[a-z_][a-z0-9_]*',table) or not re.fullmatch(r'[a-z_][a-z0-9_]*',column):
        raise ValueError('Configurazione catalogo non valida')
    codes, offset = set(), 0
    while True:
        rows = client.table(table).select(column).order(column).range(offset,offset+499).execute().data or []
        codes.update(str(r[column]).strip() for r in rows if r.get(column))
        if len(rows)<500:
            return codes
        offset += len(rows)


def load_gtin_catalog(client, *, gtins=None):
    """Authoritative GTIN -> REF comparison; never fall back to scan registrations."""
    wanted = None if gtins is None else sorted({str(g).strip() for g in gtins if g and str(g).strip().lower() != 'nan'})
    if wanted == []:
        return {}
    # Filtered requests are small; retain the complete-catalogue API for imports.
    if wanted is not None and len(wanted) > 200:
        result = {}
        for start in range(0, len(wanted), 200):
            result.update(load_gtin_catalog(client, gtins=wanted[start:start+200]))
        return result
    catalog,offset={},0
    while True:
        query = client.table('articoli_gtin').select('gtin,ref')
        if wanted is not None:
            query = query.in_('gtin', wanted)
        rows=query.order('gtin').range(offset,offset+499).execute().data or []
        for row in rows:
            gtin=str(row.get('gtin') or '').strip(); ref=str(row.get('ref') or '').strip()
            if gtin and ref:
                if gtin in catalog and catalog[gtin]!=ref:
                    raise ValueError('GTIN associato a REF discordanti nel catalogo')
                catalog[gtin]=ref
        if not rows:return catalog
        offset+=len(rows)
