"""All geometry and acquisition checks run locally, without model requests."""
from pathlib import Path
import hashlib
from PIL import Image


def regions_for_page(page):
    from label_geometry import locate_datamatrix_labels
    from label_pipeline import decode_barcodes,unique_regions,overlap
    regions=locate_datamatrix_labels(page)
    # An already isolated sticker is not another complete hospital form.
    aspect=max(page.size)/min(page.size)
    if 2<aspect<5 and len([b for b in decode_barcodes(page) if not b.get('error')])==1:
        rotation=regions[0]['rotation'] if regions else 0
        return [{'bbox':[0,0,1000,1000],'rotation':rotation,'geometry_source':'single_gs1_sticker'}]
    from linear_label_geometry import locate_linear_labels
    try:linear=locate_linear_labels(page)
    except Exception:linear=[]
    for r in linear:
        if not any(overlap(r['bbox'],q['bbox'])>.2 for q in regions):
            regions.append(dict(r,geometry_source='local_linear_markers'))
    return unique_regions([dict(r,page=1) for r in regions])


def prepare_document(path):
    from label_pipeline import render_pages
    regions=[]
    for n,page in enumerate(render_pages(path),1):
        regions.extend(dict(r,page=n) for r in regions_for_page(page))
    return {'sha256':hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            'approved':False,'labels_only_confirmed':False,'regions':regions}


def read_local(path,mode='scarico_sala'):
    from label_pipeline import (render_pages,crop_region,decode_barcodes,local_ref_evidence,
                                reconcile,verify_ref_evidence,PIPELINE_VERSION)
    from image_quality import inspect_quality,geometry_alerts,acquisition_report
    result={'items':[],'detection_warnings':[],'pipeline_version':PIPELINE_VERSION,'acquisition':[]}
    digest=hashlib.sha256(Path(path).read_bytes()).hexdigest()[:20]
    for page_number,page in enumerate(render_pages(path),1):
        regions=regions_for_page(page)
        acquisition=acquisition_report(page,regions)
        result['acquisition'].append(dict(acquisition,page=page_number))
        result['detection_warnings'].extend(acquisition['warnings'])
        result['detection_warnings'].extend(geometry_alerts(regions))
        if not regions:result['detection_warnings'].append(f'Pagina {page_number}: nessuna etichetta locale affidabile; nuova foto ravvicinata richiesta')
        for index,region in enumerate(regions,1):
            crop=crop_region(page,region['bbox']).rotate(region['rotation']+region.get('deskew_angle',0),expand=True,resample=Image.Resampling.BICUBIC,fillcolor='white')
            evidence=local_ref_evidence(crop)
            code=evidence['candidates'][0] if len(evidence.get('candidates',[]))==1 else None
            row=verify_ref_evidence(reconcile({'code':code,'lot':None,'expiry':None,'description':None},decode_barcodes(crop)),evidence)
            row.update(label_id=f'{digest}:p{page_number}:l{index}',source_document=digest,page=page_number,bbox=region['bbox'],rotation=region['rotation'],geometry_source=region.get('geometry_source'),image_quality=inspect_quality(crop))
            if not row['barcodes']:row['warning']=' · '.join(filter(None,[row.get('warning'),'DataMatrix non decodificato: acquisire una nuova foto più ravvicinata']))
            result['items'].append(row)
    return result
