#!/usr/bin/env python3
"""Offline source-resolution study. Downsampling only; never calls a model.

Native long-side above the original is NOT available higher-resolution evidence.
Ground-truth boxes are scoring only; detection uses actual local geometry.
"""
import argparse,csv,json,sys,hashlib
from pathlib import Path
from collections import Counter
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from label_pipeline import render_pages,crop_region,decode_barcodes
from local_label_reader import regions_for_page
from evaluate_ocr import load_truth
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--images',type=Path,required=True);p.add_argument('--truth',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
p.add_argument('--annotations',type=Path)
p.add_argument('--decoder',choices=['v14','v15'],default='v15')
p.add_argument('--scales',default='1,.75,.5,.375,.25')
a=p.parse_args()
if a.decoder=='v14':
 import importlib.util
 spec=importlib.util.spec_from_file_location('decoder_v14',Path(__file__).resolve().parents[1]/'tests/evaluation/decoder_v14_reference.py')
 legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy);decode_barcodes=legacy.decode_barcodes
truth,_,_=load_truth(a.images,a.truth,a.annotations)
rows=[]
for name,expected in truth.items():
 for page_number,page in enumerate(render_pages(a.images/name),1):
  wanted=Counter((r['lot'],r['expiry']) for r in expected if r['page']==page_number)
  for scale in map(float,a.scales.split(',')):
   if not 0<scale<=1:raise ValueError('Only real-source resolution and downsampling are valid here')
   resized=page.resize(tuple(max(1,round(v*scale)) for v in page.size),Image.Resampling.LANCZOS)
   regions=regions_for_page(resized);observed=[]
   for r in regions:
    crop=crop_region(resized,r['bbox']).rotate(r['rotation']+r.get('deskew_angle',0),expand=True,resample=Image.Resampling.BICUBIC,fillcolor='white')
    if a.decoder=='v15':
     from datamatrix_reader import decode_label_region
     decoded=decode_label_region(resized,r)
    else:decoded=decode_barcodes(crop)
    observed.extend(b for b in decoded if not b.get('error'))
   count=Counter((b.get('lot'),b.get('expiry')) for b in observed)
   correct=sum((count & wanted).values())
   row=dict(decoder=a.decoder,file=name,page=page_number,source_width=page.width,source_height=page.height,scale=scale,width=resized.width,height=resized.height,
    expected=sum(wanted.values()),local_regions=len(regions),decoded_payloads=len(observed),correct=correct,wrong=sum((count-wanted).values()),rate=correct/max(1,sum(wanted.values())))
   rows.append(row);print(json.dumps(row),flush=True)
a.out.parent.mkdir(parents=True,exist_ok=True)
with a.out.open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
