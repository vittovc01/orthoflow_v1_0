"""Live, read-only OCR regression. Requires explicit original PDF and OCR secrets.

python tools/verify_santa_lucia.py /path/to/original.pdf
No Supabase access, no stock writes; verifies geometry AND individual identities.
"""
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ai_ocr import analyze_document
from label_pipeline import overlap

manifest=json.loads(Path('tests/fixtures/santa_lucia/manifest.json').read_text())
path=Path(sys.argv[1])
if hashlib.sha256(path.read_bytes()).hexdigest()!=manifest['source_sha256']:
    raise SystemExit('PDF diverso dal documento originale annotato')
result=analyze_document(str(path))
errors=[]
matched=set()
for item in result['items']:
    if item.get('page')!=1:
        errors.append('Pagina inattesa');continue
    source=item['bbox']
    upright=[1000-source[2],1000-source[3],1000-source[0],1000-source[1]]
    candidates=[r for r in manifest['labels'] if overlap(r['bbox_upright'],upright)>=.6]
    if len(candidates)!=1:
        errors.append('Ritaglio assente, ambiguo o misto: '+item['label_id']);continue
    target=candidates[0]
    if target['label_id'] in matched:
        errors.append('Etichetta letta due volte: '+target['label_id'])
    matched.add(target['label_id'])
    for field in ('code','lot','expiry'):
        if item.get(field)!=target[field]:
            errors.append(f"{target['label_id']} {field}: ottenuto {item.get(field)!r}; atteso {target[field]!r}")
for target in manifest['labels']:
    if target['label_id'] not in matched:
        errors.append('Etichetta non individuata: '+target['label_id'])
if len(result['items'])!=16:
    errors.append(f"Conteggio {len(result['items'])}, atteso 16")
print(json.dumps({'detected':len(result['items']),'matched':len(matched),'errors':errors},indent=2))
raise SystemExit(1 if errors else 0)
