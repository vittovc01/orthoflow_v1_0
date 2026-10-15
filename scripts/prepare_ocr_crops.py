#!/usr/bin/env python3
"""Local-only proposal manifest and per-label previews. No external calls.
Review previews locally, remove unsafe regions, then set approved and
labels_only_confirmed true for each document. Never use ground truth as a crop
oracle: the manifest is generated exclusively from local image geometry.
"""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from local_label_reader import prepare_document
from label_pipeline import render_pages,crop_region
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--images',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True);manifest={'version':1,'documents':{}}
for path in sorted(a.images.rglob('*')):
 if not path.is_file() or path.suffix.lower() not in {'.jpg','.jpeg','.png','.webp','.pdf'}:continue
 proposal=prepare_document(path);manifest['documents'][proposal['sha256']]=proposal
 pages=render_pages(path)
 for n,region in enumerate(proposal['regions'],1):
  crop_region(pages[region['page']-1],region['bbox']).save(a.out/f'{proposal["sha256"][:16]}_{n:02}.png')
(a.out/'privacy_manifest.json').write_text(json.dumps(manifest,indent=2))
print('Proposte locali pronte. Nessun invio esterno. Rivedere ogni ritaglio prima di approvare il manifest.')
