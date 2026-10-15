#!/usr/bin/env python3
"""Read-only OCR evaluation. Never creates a Supabase client or archives a review.

live: exact production analyzer, including its real model calls.
local: actual local geometry/ZXing/Tesseract components; NOT an AI/live benchmark.
replay: previously recorded predictions; NOT a fresh model validation.
Ground-truth boxes are used ONLY for scoring, never to locate or read a label.
"""
import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from ocr_review import canonical_item, normalize_expiry, aggregate_review

SUPPORTED = {'.jpg','.jpeg','.png','.webp','.pdf'}
CRITICAL = {'ref':'code','lotto':'lot','scadenza':'expiry'}
REQUIRED_CONDITIONS = {'overlap','touching','clipped','skew','glare','dark','blur',
                       'cross_photo_duplicate','barcode_unreadable','text_unreadable','barcode_text_conflict'}
REVIEW_STATES = {'missing','conflict','invalid','unverified','unknown_catalogue','possible_duplicate'}
REPORT_COLUMNS = ['priority','row_type','repeat','case_id','file','truth_label','predicted_label',
    'field','expected','predicted','correct','flagged','silent_error','method','matching','condition','problem']


def sha(value):
    return hashlib.sha256(value).hexdigest()


def load_truth(root, path, annotations_path=None):
    root = root.resolve()
    annotations = json.loads(annotations_path.read_text()) if annotations_path else {'labels':[]}
    index = {(a['file'],int(a['truth_index'])):a for a in annotations.get('labels',[])}
    if len(index)!=len(annotations.get('labels',[])):
        raise ValueError('Annotazioni ripetute per lo stesso file/truth_index')
    files, offsets = defaultdict(list), Counter()
    with path.open(encoding='utf-8-sig',newline='') as stream:
        reader = csv.DictReader(stream)
        if not {'file','ref','lotto','scadenza','quantita'}<=set(reader.fieldnames or []):
            raise ValueError('Colonne richieste: file,ref,lotto,scadenza,quantita')
        for record in reader:
            name = record['file'].strip()
            source = (root/name).resolve()
            if not source.is_relative_to(root) or source.suffix.lower() not in SUPPORTED or not source.is_file():
                raise ValueError('File di prova non valido o assente: '+name)
            quantity = int(record['quantita'])
            if not 1<=quantity<=500:
                raise ValueError('quantita deve essere un intero tra 1 e 500')
            expiry = record['scadenza'].strip()
            if expiry:
                normalized, precision = normalize_expiry(expiry)
                if not normalized or precision!='day':
                    raise ValueError('La verità deve contenere una scadenza completa o un campo vuoto: '+name)
                expiry = normalized
            for _ in range(quantity):
                i = offsets[name]; offsets[name]+=1
                a = index.get((name,i),{})
                box = a.get('bbox')
                if box is not None and (len(box)!=4 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in box)
                        or not 0<=box[0]<box[2]<=1000 or not 0<=box[1]<box[3]<=1000):
                    raise ValueError('Bounding box ground truth non valida')
                files[name].append({'file':name,'truth_index':i,'code':record['ref'].strip(),
                    'lot':record['lotto'].strip(),'expiry':expiry,'bbox':box,'page':a.get('page',1),
                    'case_id':a.get('case_id',name),'physical_id':a.get('physical_id',f'{name}:{i}'),
                    'conditions':a.get('conditions',[])})
    if not files:
        raise ValueError('Ground truth vuota')
    if set(index)-{(name,r['truth_index']) for name,rows in files.items() for r in rows}:
        raise ValueError('Annotazioni senza una riga corrispondente nel CSV')
    for name,rows in files.items():
        if len({r['case_id'] for r in rows})!=1:
            raise ValueError('Un file non può appartenere a più scarichi nel medesimo test')
    all_images = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.suffix.lower() in SUPPORTED}
    unlisted = sorted(all_images-set(files))
    return dict(files), annotations, unlisted


def iou(a,b):
    intersection = max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    union = (a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection
    return intersection/union if union else 0


def assignment(cost):
    """Hungarian assignment, O(n³), including dummy rows/columns. No SciPy required."""
    n=len(cost)
    if not n:return []
    u=[0.]*(n+1);v=[0.]*(n+1);p=[0]*(n+1);way=[0]*(n+1)
    for i in range(1,n+1):
        p[0]=i;j0=0;minimum=[float('inf')]*(n+1);used=[False]*(n+1)
        while True:
            used[j0]=True;i0=p[j0];delta=float('inf');j1=0
            for j in range(1,n+1):
                if not used[j]:
                    current=cost[i0-1][j-1]-u[i0]-v[j]
                    if current<minimum[j]:minimum[j]=current;way[j]=j0
                    if minimum[j]<delta:delta=minimum[j];j1=j
            for j in range(n+1):
                if used[j]:u[p[j]]+=delta;v[j]-=delta
                else:minimum[j]-=delta
            j0=j1
            if not p[j0]:break
        while True:
            j1=way[j0];p[j0]=p[j1];j0=j1
            if not j0:break
    return [(p[j]-1,j-1) for j in range(1,n+1)]


def match_labels(truth,predictions):
    n,m=len(truth),len(predictions);cost=[]
    for i in range(n+m):
        row=[]
        for j in range(n+m):
            if i>=n and j>=m:value=0
            elif i>=n or j>=m:value=1
            elif truth[i].get('bbox') is not None:
                overlap=iou(truth[i]['bbox'],predictions[j].get('bbox') or [0,0,0,0])
                value=1-overlap if overlap>=.3 and truth[i]['page']==predictions[j].get('page',1) else 1e6
            else:
                # Diagnostic only. This cannot establish spatial recall or certify
                # per-field errors when identity itself is wrong. Gate stays blocked.
                value=.1+.25*sum(str(truth[i].get(k) or '')!=str(predictions[j].get(k) or '') for k in CRITICAL.values())
            row.append(value)
        cost.append(row)
    pairs=[(i,j) for i,j in assignment(cost) if i<n and j<m and cost[i][j]<1]
    return pairs, sorted(set(range(n))-{i for i,j in pairs}), sorted(set(range(m))-{j for i,j in pairs})


def field_flag(item,field):
    """Generic mandatory operator review is NOT evidence that a bad field was caught."""
    assessment=(item.get('assessment') or {}).get('fields',{}).get(field,{})
    if assessment.get('status') in REVIEW_STATES or not item.get(field):return True
    warning=str(item.get('warning') or '').lower()
    aliases={'code':('ref','codice','code'),'lot':('lotto','lot'),'expiry':('scadenza','expiry')}
    return any(word in warning for word in aliases[field])


def condition_flag(item,condition,warnings):
    issues=' '.join((item or {}).get('assessment',{}).get('issues',[])).lower()
    text=' '.join([issues,str((item or {}).get('warning') or ''),' '.join(warnings)]).lower()
    # A generic "manual review required" does not count as an image-quality alert.
    markers={'clipped':('bordo','tagli','tronc','clipp'),'overlap':('sovrapp','più etichette','mixed','confini'),
      'touching':('toccano','sovrapp','più etichette','mixed','confini'),'skew':('inclin','rotaz','geometr'),
      'glare':('rifless','glare'),'dark':('luminos','buia','dark'),'blur':('sfocat','blur'),
      'cross_photo_duplicate':('duplic','più foto','cross_photo'),
      'barcode_text_conflict':('conflitto','discordant'),
      'barcode_unreadable':('datamatrix non leggibile','barcode non leggibile','payload gs1 assente'),
      'text_unreadable':('non letto','unreadable','incomplet','lettura fallita','unverified','missing')}
    if condition=='cross_photo_duplicate' and (item or {}).get('cross_photo_candidates'):return True
    quality=(item or {}).get('image_quality',{}).get('conditions',[])
    return condition in quality or any(s in text for s in markers.get(condition,()))


def local_analyzer(path,mode='scarico_sala'):
    """Actual offline components, no oracle boxes/identifiers and no AI mock result."""
    from local_label_reader import read_local
    return read_local(path,mode=mode)


def live_analyzer(model,privacy_manifest=None):
    if not os.environ.get('OPENAI_API_KEY'):
        raise RuntimeError('OPENAI_API_KEY non configurata: valutazione live NON ESEGUITA')
    from openai import OpenAI
    from ai_ocr import ITEM_PROPERTIES,ITEM_REQUIRED,_parse_response
    from label_pipeline import analyze_labels
    if not os.environ.get('OPENAI_API_KEY'):
        raise RuntimeError('OPENAI_API_KEY non configurata: valutazione live NON ESEGUITA')
    client=OpenAI(api_key=os.environ['OPENAI_API_KEY'],timeout=60,max_retries=1)
    schema={'type':'object','properties':ITEM_PROPERTIES,'required':ITEM_REQUIRED,'additionalProperties':False}
    # Same production analyzer; deliberately bypass usage tracking/storage adapters.
    return lambda path,mode='scarico_sala':analyze_labels(path,client,model,schema,_parse_response,privacy_approval=(privacy_manifest or {}).get(sha(Path(path).read_bytes())))


def evaluate_case(case_id,truth_by_file,prediction,repeat):
    reports=[];counters=Counter();field_counts={k:Counter() for k in CRITICAL};matched_by_truth={}
    items=[canonical_item(r) for r in prediction.get('items',[])]
    names=list(truth_by_file)
    warnings=prediction.get('detection_warnings') or []
    for document_index,name in enumerate(names):
        expected=truth_by_file[name]
        document=next((d for d in prediction.get('documents',[]) if d.get('index')==document_index),{})
        observation_index=document.get('duplicate_of',document_index) if document.get('status')=='duplicate' else document_index
        observed=[r for r in items if r.get('document_index',0)==observation_index]
        pairs,missing,extra=match_labels(expected,observed)
        counters.update(expected=len(expected),found=len(observed),matched=len(pairs),missing=len(missing),extra=len(extra))
        for i,j in pairs:
            target,item=expected[i],observed[j]
            matched_by_truth[(name,i)]=item
            spatial=target.get('bbox') is not None
            counters['spatial_matches']+=int(spatial)
            reports.append(dict(row_type='label',file=name,truth_label=target['physical_id'],predicted_label=item.get('label_id'),
                                correct=True,method=' / '.join(sorted({str(f.get('method','missing')) for f in item.get('assessment',{}).get('fields',{}).values()})),
                                matching='spatial' if spatial else 'heuristic_unverified'))
            for column,field in CRITICAL.items():
                value=str(item.get(field) or '').strip();wanted=str(target.get(field) or '')
                if field=='expiry' and value:value=normalize_expiry(value)[0] or value
                flagged=field_flag(item,field)
                correct=value==wanted if wanted else None
                silent=(correct is False and not flagged) or (not wanted and bool(value) and not flagged)
                metric=field_counts[column];metric['total']+=1;metric['flagged']+=int(flagged)
                metric['correct']+=int(correct is True);metric['wrong']+=int(correct is False)
                metric['unknown_truth']+=int(correct is None);metric['silent']+=int(silent)
                counters['silent_errors']+=int(silent)
                reports.append(dict(row_type='field',file=name,truth_label=target['physical_id'],predicted_label=item.get('label_id'),
                  field=column,expected=wanted,predicted=value,correct=correct,flagged=flagged,silent_error=bool(silent),
                  method=item.get('assessment',{}).get('fields',{}).get(field,{}).get('method','missing'),
                  matching='spatial' if spatial else 'heuristic_unverified',problem='errore_silenzioso' if silent else 'campo_errato_o_assente' if correct is False else 'da_verificare' if flagged else ''))
        for i in missing:
            target=expected[i]
            reports.append(dict(row_type='label',file=name,truth_label=target['physical_id'],correct=False,
                                flagged=bool(warnings),problem='etichetta_non_trovata'))
            for column,field in CRITICAL.items():
                field_counts[column].update(total=1,wrong=int(bool(target.get(field))),missing_label=1,flagged=1)
                reports.append(dict(row_type='field',file=name,truth_label=target['physical_id'],field=column,
                    expected=target.get(field),predicted='',correct=False if target.get(field) else None,
                    flagged=True,silent_error=False,method='missing',problem='etichetta_non_trovata'))
        for j in extra:
            item=observed[j]
            reports.append(dict(row_type='label',file=name,predicted_label=item.get('label_id'),correct=False,problem='falso_positivo'))
            for column,field in CRITICAL.items():
                if item.get(field) and not field_flag(item,field):
                    counters['silent_errors']+=1
                    field_counts[column].update(total=1,wrong=1,silent=1,false_positive=1)
                    reports.append(dict(row_type='field',file=name,predicted_label=item.get('label_id'),field=column,
                        predicted=item[field],correct=False,flagged=False,silent_error=True,problem='campo_sicuro_su_falso_positivo'))
        for i,target in enumerate(expected):
            for condition in target['conditions']:
                flagged=condition_flag(matched_by_truth.get((name,i)),condition,warnings)
                counters['condition_expected']+=1;counters['condition_flagged']+=int(flagged)
                reports.append(dict(row_type='condition',file=name,truth_label=target['physical_id'],condition=condition,
                                    flagged=flagged,correct=flagged,problem='' if flagged else 'condizione_non_segnalata'))
    # Quantity truth counts physical units, not appearances of the same sticker.
    units={}
    for expected in truth_by_file.values():
        for target in expected:
            key=target['physical_id'];identity=(target['code'],target['lot'],target['expiry'])
            if key in units and units[key]!=identity:raise ValueError('physical_id con verità discordante')
            units[key]=identity
    counters['physical_expected']=len(units)
    counters['physical_matched']=len({truth_by_file[name][i]['physical_id'] for name,i in matched_by_truth})
    expected_qty=Counter((r[0],r[1]) for r in units.values())
    try:
        groups=aggregate_review(items)
        actual_qty=Counter({(g['code'],g['lot']):g['quantity'] for g in groups})
        aggregation_error=None
    except ValueError as exc:
        actual_qty=Counter();aggregation_error=str(exc);counters['aggregation_unavailable']+=1
    for identity in sorted(set(expected_qty)|set(actual_qty)):
        actual=actual_qty.get(identity) if not aggregation_error else None
        correct=actual==expected_qty.get(identity,0) if actual is not None else None
        counters['quantity_wrong']+=int(correct is False)
        counters['quantity_unresolved']+=int(correct is None)
        reports.append(dict(row_type='quantity',field='ref+lotto',expected=expected_qty.get(identity,0),predicted=actual,
            correct=correct,flagged=bool(aggregation_error),problem=aggregation_error or ('' if correct else 'quantita_aggregata_errata'),
            truth_label=' / '.join(identity)))
    for row in reports:
        row.update(case_id=case_id,repeat=repeat)
        row['priority']=0 if row.get('silent_error') else 1 if row.get('problem') and row.get('problem')!='da_verificare' else 2
    return reports,counters,field_counts


def evaluate(root,truth_path,out,*,mode='local',annotations_path=None,model='gpt-4.1',repeats=1,
             predictions_path=None,compare_path=None,min_labels=300,min_cases=50,gtin_catalog_path=None,privacy_manifest_path=None):
    from ocr_service import analyze_documents
    from ocr_repository import OriginalDocument,without_images
    truth,annotations,unlisted=load_truth(root,truth_path,annotations_path)
    groups=defaultdict(dict)
    for name,rows in truth.items():groups[rows[0]['case_id']][name]=rows
    source_hashes={name:sha((root/name).read_bytes()) for name in sorted(truth)}
    dataset_hash=sha(json.dumps({'truth':truth,'source_hashes':source_hashes},sort_keys=True).encode())
    code_files=['evaluate_ocr.py','ocr_service.py','ocr_review.py','label_pipeline.py','label_geometry.py',
                'sticker_geometry.py','linear_label_geometry.py','image_quality.py','ai_ocr.py',
                'datamatrix_reader.py','local_label_reader.py','ocr_privacy.py','gtin_catalog.py']
    pipeline_hash=sha(b''.join((Path(__file__).parent/p).read_bytes() for p in code_files))
    summary={'silent_errors':None,'accepted':False,'status':'NOT_RUN','mode':mode,'model':model if mode=='live' else None,
        'generated_at':datetime.now(timezone.utc).isoformat(),'dataset_sha256':dataset_hash,'pipeline_sha256':pipeline_hash,
        'files':len(truth),'cases':len(groups),'unique_label_appearances':sum(len(v) for v in truth.values()),
        'unique_physical_labels':len({(r['case_id'],r['physical_id']) for rows in truth.values() for r in rows}),
        'annotations_complete':all(r.get('bbox') is not None for rows in truth.values() for r in rows),
        'truth_manual_review_confirmed':bool(annotations.get('manual_truth_verified',False)),
        'gtin_catalog_sha256':sha(gtin_catalog_path.read_bytes()) if gtin_catalog_path else None,
        'privacy_manifest_sha256':sha(privacy_manifest_path.read_bytes()) if privacy_manifest_path else None,
        'repeats':repeats,'unlisted_files':unlisted,'python':platform.python_version(),
        'packages':{},'tesseract':None}
    try:
        summary['tesseract']=subprocess.run(['tesseract','--version'],capture_output=True,text=True,timeout=5,check=True).stdout.splitlines()[0]
    except (OSError,subprocess.SubprocessError):pass
    for package in ('Pillow','zxing-cpp','opencv-python-headless','openai'):
        try:summary['packages'][package]=importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:summary['packages'][package]=None
    out.mkdir(parents=True,exist_ok=True)
    try:
        privacy_manifest=json.loads(privacy_manifest_path.read_text()).get('documents',{}) if privacy_manifest_path else None
        if mode!='replay':
            import cv2,zxingcpp,fitz
            if not __import__('shutil').which('tesseract'):
                raise RuntimeError('Tesseract assente: valutazione non eseguibile')
        reader=live_analyzer(model,privacy_manifest) if mode=='live' else local_analyzer
        from gtin_catalog import read_catalog
        gtin_catalog=read_catalog(gtin_catalog_path) if gtin_catalog_path else None
        replay=json.loads(predictions_path.read_text()) if mode=='replay' and predictions_path else None
        if mode=='replay' and (not replay or replay.get('dataset_sha256')!=dataset_hash):
            raise ValueError('Replay assente o riferito a un dataset diverso')
        reports=[];total=Counter();fields={k:Counter() for k in CRITICAL};recorded={}
        for repeat in range(1,repeats+1):
            for case_id,files in groups.items():
                docs=[OriginalDocument(name,(root/name).read_bytes()) for name in files]
                prediction=(replay['predictions'][f'{repeat}:{case_id}'] if replay else analyze_documents(docs,analyzer=reader,gtin_catalog=gtin_catalog))
                recorded[f'{repeat}:{case_id}']=without_images(prediction)
                rows,counts,metrics=evaluate_case(case_id,files,prediction,repeat)
                reports.extend(rows);total.update(counts)
                for field in fields:fields[field].update(metrics[field])
                total['failed_documents']+=sum(d.get('status')=='failed' for d in prediction.get('documents',[]))
        expected=total['physical_expected']; matched=total['physical_matched']
        conditions=set(c for rows in truth.values() for r in rows for c in r['conditions'])
        accuracy=sum(v['correct'] for v in fields.values())/max(1,sum(v['total'] for v in fields.values()))
        review_rate=sum(v['flagged'] for v in fields.values())/max(1,sum(v['total'] for v in fields.values()))
        summary.update(status='COMPLETED',silent_errors=total['silent_errors'],counts=dict(total),
            recall=matched/expected if expected else None,fields={k:dict(v) for k,v in fields.items()},
            exact_field_accuracy=accuracy,field_review_rate=review_rate,conditions_covered=sorted(conditions),
            spatial_recall=matched/expected if summary['annotations_complete'] else None)
        reasons=[]
        checks=[(mode=='live','Modello live non eseguito'),(repeats>=3,'Servono almeno tre ripetizioni live'),
          (summary['silent_errors']==0,'Errori silenziosi presenti'),(summary['annotations_complete'],'Mancano box indipendenti'),
          (summary['truth_manual_review_confirmed'],'Verità manuale non controverificata'),
          (summary['unique_physical_labels']>=min_labels,f'Servono almeno {min_labels} etichette reali annotate'),
          (len(groups)>=min_cases,f'Servono almeno {min_cases} scarichi indipendenti'),
          (not unlisted,'Foto/PDF senza ground truth'),(matched==expected,'Etichette mancanti'),
          (total['extra']==0,'Falsi positivi'),(accuracy>=.98,'Accuratezza esatta campi inferiore al 98%'),
          (review_rate<=.15,'Più del 15% dei campi da verificare'),
          (total['quantity_wrong']==0 and total['quantity_unresolved']==0,'Quantità errate o non risolte'),
          (REQUIRED_CONDITIONS<=conditions,'Casi limite non tutti rappresentati'),
          (total['condition_expected']==total['condition_flagged'],'Condizioni difficili non tutte segnalate'),
          (total['failed_documents']==0,'Documenti non analizzati')]
        reasons=[reason for ok,reason in checks if not ok]
        summary.update(accepted=not reasons,gate_reasons=reasons,
            acceptance_thresholds={'silent_errors':0,'recall':1.0,'false_positives':0,'exact_field_accuracy':.98,
             'max_field_review_rate':.15,'quantity_errors_or_unresolved':0,'min_labels':min_labels,'min_cases':min_cases,'live_repeats':3})
        reports.sort(key=lambda r:(r['priority'],r['case_id'],r.get('file',''),r.get('truth_label',''),r['row_type']))
        with (out/'report.csv').open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=REPORT_COLUMNS,extrasaction='ignore');writer.writeheader()
            writer.writerow({'priority':-1,'row_type':'SUMMARY_SILENT_ERRORS','field':'silent_errors','predicted':summary['silent_errors'],
                             'problem':'ACCEPTED' if summary['accepted'] else 'BLOCKED: '+'; '.join(reasons)})
            writer.writerows(reports)
        with (out/'problems.csv').open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=REPORT_COLUMNS,extrasaction='ignore');writer.writeheader()
            writer.writerows(r for r in reports if r.get('problem'))
        from gtin_catalog import missing_gtins_csv
        (out/'gtin_mancanti.csv').write_text(missing_gtins_csv([item for prediction in recorded.values() for item in prediction.get('items',[])]),encoding='utf-8')
        # Do not include hospital header/clinical record in replay output.
        for prediction in recorded.values():
            for key in ('clinic_name','clinical_record','procedure_date','surgeon'):prediction.pop(key,None)
        (out/'predictions.json').write_text(json.dumps({'dataset_sha256':dataset_hash,'mode':mode,'model':summary['model'],
            'predictions':recorded},ensure_ascii=False,indent=2),encoding='utf-8')
        if compare_path:
            prior=json.loads(compare_path.read_text())
            if prior.get('dataset_sha256')!=dataset_hash:raise ValueError('Confronto rifiutato: dataset diversi')
            summary['comparison']={key:{'baseline':prior.get(key),'current':summary.get(key)} for key in
                ('mode','model','silent_errors','recall','exact_field_accuracy','field_review_rate')}
    except Exception as exc:
        # Unknown metrics must never appear as reassuring zeroes.
        summary.update(status='NOT_RUN' if summary['silent_errors'] is None else 'ERROR',accepted=False,
                       gate_reasons=[__import__('safe_ocr_logs').redact(f'{type(exc).__name__}: {exc}')[0]])
    if summary['status']!='COMPLETED':
        with (out/'report.csv').open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=REPORT_COLUMNS);writer.writeheader()
            writer.writerow({'priority':-1,'row_type':'SUMMARY_SILENT_ERRORS','field':'silent_errors','predicted':'NON_MISURATI','problem':'; '.join(summary['gate_reasons'])})
        (out/'problems.csv').write_text('row_type,problem\nNOT_RUN,Valutazione non completata\n',encoding='utf-8')
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    return summary


def main(argv=None):
    import logging
    for logger in ('openai','httpx','httpcore'):
        logging.getLogger(logger).setLevel(logging.CRITICAL+1)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images',type=Path,required=True);parser.add_argument('--truth',type=Path,required=True)
    parser.add_argument('--gtin-catalog',type=Path);parser.add_argument('--privacy-manifest',type=Path)
    parser.add_argument('--annotations',type=Path);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--mode',choices=['live','local','replay'],default='live')
    parser.add_argument('--model',default=os.getenv('SCARICO_LABEL_MODEL','gpt-4.1'))
    parser.add_argument('--repeats',type=int,default=1);parser.add_argument('--predictions',type=Path)
    parser.add_argument('--compare',type=Path);parser.add_argument('--min-labels',type=int,default=300)
    parser.add_argument('--min-cases',type=int,default=50)
    args=parser.parse_args(argv)
    if not 1<=args.repeats<=10 or args.min_labels<1 or args.min_cases<1:parser.error('Soglie/ripetizioni non valide')
    try:
        result=evaluate(args.images,args.truth,args.out,mode=args.mode,annotations_path=args.annotations,
            model=args.model,repeats=args.repeats,predictions_path=args.predictions,compare_path=args.compare,
            min_labels=args.min_labels,min_cases=args.min_cases,gtin_catalog_path=args.gtin_catalog,privacy_manifest_path=args.privacy_manifest)
    except (ValueError,OSError) as exc:
        print('VALUTAZIONE NON ESEGUITA:',__import__('safe_ocr_logs').redact(str(exc))[0],file=sys.stderr);return 3
    print('ERRORI SILENZIOSI:',result['silent_errors'] if result['silent_errors'] is not None else 'NON MISURATI')
    print('ESITO:', 'ACCEPTED' if result['accepted'] else 'BLOCKED', '| modalità:',result['mode'])
    print(json.dumps({k:result.get(k) for k in ('status','recall','fields','counts','gate_reasons')},ensure_ascii=False,indent=2))
    problem_path=args.out/'problems.csv'
    if result['status']=='COMPLETED' and problem_path.exists():
        with problem_path.open(encoding='utf-8-sig',newline='') as stream:
            for r in csv.DictReader(stream):
                print('CASO:',r['file'],r['truth_label'] or r['predicted_label'],r['field'],r['problem'])
    return 0 if result['accepted'] else 4 if result['status']=='NOT_RUN' else 2


if __name__=='__main__':sys.exit(main())
