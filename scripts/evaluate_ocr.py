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


def metrics(regions):
    found=set();extra=0
    for r in regions:
        a=r['bbox'];matches=[]
        for i,b in enumerate(TRUTH):
            intersection=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
            cover=intersection/((b[2]-b[0])*(b[3]-b[1]))
            if cover>=.8:matches.append((cover,i))
        matches=[m for m in matches if m[1] not in found]
        if matches:found.add(max(matches)[1])
        else:extra+=1
    return {'regions':len(regions),'extra_regions':extra,'true_labels_found':len(found),
            'true_labels':len(TRUTH),'recall':len(found)/len(TRUTH)}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--input',default='tests/fixtures/federico_labels.png')
    parser.add_argument('--output');args=parser.parse_args()
    page=render_pages(args.input)[0]
    before=locate_datamatrix_labels(page)
    accepted,rejected=safe_product_regions(page,before)
    result={'scope':'Offline local geometry; historical AI response unavailable. No end-to-end OCR accuracy claim.',
        'before_local_finder':metrics(before),'after_product_gate':metrics(accepted),
        'recoverable_rejected':len(rejected),'documented_screenshot_extra_regions_minimum':1,
        'header_extraction_external_calls':0}
    encoded=json.dumps(result,indent=2)
    print(encoded)
    if args.output:Path(args.output).write_text(encoded+'\n')
    if len(accepted)!=7 or metrics(accepted)['extra_regions']:raise SystemExit(1)

if __name__=='__main__':main()
