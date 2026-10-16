"""Offline region evaluation. Never sends a document to any external service.

The baseline is the previous local finder, NOT an invented reproduction of
unavailable historical AI responses. --input can point to the original PDF.
"""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from label_pipeline import render_pages
from label_geometry import locate_datamatrix_labels
from region_privacy import safe_product_regions

TRUTH=[[94,438,303,488],[306,438,514,493],[524,440,732,492],
       [100,489,308,541],[305,489,516,545],[538,489,732,565],[94,547,302,597]]


def metrics(regions, truth=TRUTH):
    found=set();extra=0
    for r in regions:
        a=r['bbox'];matches=[]
        for i,b in enumerate(truth):
            intersection=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
            cover=intersection/((b[2]-b[0])*(b[3]-b[1]))
            if cover>=.8:matches.append((cover,i))
        matches=[m for m in matches if m[1] not in found]
        if matches:found.add(max(matches)[1])
        else:extra+=1
    return {'regions':len(regions),'extra_regions':extra,'true_labels_found':len(found),
            'true_labels':len(truth),'recall':len(found)/len(truth)}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--input',default='tests/fixtures/federico_labels.png')
    parser.add_argument('--truth-json',help='JSON array of reference boxes for this input (0..1000)')
    parser.add_argument('--read-fields',action='store_true',help='Read local literal REF evidence and GS1 fields; no external calls')
    parser.add_argument('--output');args=parser.parse_args()
    truth=json.loads(Path(args.truth_json).read_text()) if args.truth_json else TRUTH
    if not truth:parser.error('At least one reference label is required')
    page=render_pages(args.input)[0]
    before=locate_datamatrix_labels(page)
    accepted,rejected=safe_product_regions(page,before)
    result={'scope':'Offline local geometry; historical AI response unavailable. No end-to-end OCR accuracy claim.',
        'before_local_finder':metrics(before,truth),'after_product_gate':metrics(accepted,truth),
        'recoverable_rejected':len(rejected),
        'header_extraction_external_calls':0}
    if args.read_fields:
        from label_pipeline import crop_region,decode_barcodes,local_ref_evidence
        from product_anchors import align_product_crop
        readings=[]
        for region in accepted:
            crop=crop_region(page,region['bbox']).rotate(region['rotation']+region.get('deskew_angle',0),expand=True)
            crop,_=align_product_crop(crop)
            readings.append({'bbox':region['bbox'],'ref_candidates':local_ref_evidence(crop)['candidates'],
                             'decoded':[{'gtin':b.get('gtin'),'lot':b.get('lot'),'expiry':b.get('expiry')}
                                        for b in decode_barcodes(crop) if not b.get('error')]})
        result['local_field_readings']=readings
        result['literal_ref_read']=sum(len(r['ref_candidates'])==1 for r in readings)
        result['lot_and_expiry_decoded']=sum(len(r['decoded'])==1 and bool(r['decoded'][0]['lot']) and bool(r['decoded'][0]['expiry']) for r in readings)
    encoded=json.dumps(result,indent=2)
    print(encoded)
    if args.output:Path(args.output).write_text(encoded+'\n')
    if metrics(accepted,truth)['recall']!=1 or metrics(accepted,truth)['extra_regions']:raise SystemExit(1)

if __name__=='__main__':main()
