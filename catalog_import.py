"""Validate a complete GTIN catalogue before a staging-only atomic import."""
import csv
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse

PRODUCTION_PROJECTS={'foawqtscqtwhpkbfbibj'}


def valid_gtin(value):
    return (bool(re.fullmatch(r'[0-9]{14}',value)) and
            (sum(int(c)*(3 if i%2==0 else 1) for i,c in enumerate(value[:-1][::-1]))+int(value[-1]))%10==0)


def prepare_catalog(path, *, source_version):
    path=Path(path)
    source_hash=hashlib.sha256(path.read_bytes()).hexdigest()
    rows={}; observed_refs={}; discarded=[]; input_count=0
    with path.open(encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream)
        if not {'gtin','ref'}<=set(reader.fieldnames or []):
            raise ValueError('CSV richiesto: gtin,ref; opzionali descrizione,categoria')
        for number,raw in enumerate(reader,2):
            input_count+=1
            gtin=str(raw.get('gtin') or '').strip(); ref=str(raw.get('ref') or '').strip()
            # Conflicts are fatal even when one of the competing records is invalid.
            if gtin in observed_refs and observed_refs[gtin]!=ref:
                raise ValueError(f'GTIN {gtin}: REF discordanti {observed_refs[gtin]} / {ref}; nessun import')
            observed_refs[gtin]=ref
            if not valid_gtin(gtin) or not ref:
                discarded.append({'line':number,'reason':'GTIN non valido o REF vuoto'})
                continue
            row={'gtin':gtin,'ref':ref,'descrizione':str(raw.get('descrizione') or '').strip() or None,
                 'categoria':str(raw.get('categoria') or '').strip() or None}
            if gtin in rows:
                if rows[gtin]!=row:
                    raise ValueError(f'GTIN {gtin}: metadati discordanti nelle righe duplicate')
                discarded.append({'line':number,'reason':'duplicato identico nel file'})
                continue
            rows[gtin]=row
    if not rows:raise ValueError('Nessuna riga valida nel catalogo')
    return {'rows':list(rows.values()),'source_file':path.name,'source_version':source_version,
            'source_sha256':source_hash,'input_rows':input_count,'discarded':discarded,
            'missing_categories':sum(not r['categoria'] for r in rows.values())}


def staging_project(url, expected_ref):
    host=urlparse(url).hostname
    if not expected_ref or expected_ref in PRODUCTION_PROJECTS or host!=f'{expected_ref}.supabase.co':
        raise ValueError('Import consentito solo su progetto staging separato; produzione bloccata')
    return expected_ref


def import_supabase_staging(payload, *, url, key, expected_ref, staging_confirmed=False):
    if not staging_confirmed:raise ValueError('Identificazione esplicita dello staging richiesta')
    staging_project(url,expected_ref)
    from supabase import create_client
    # One RPC, one transaction, no partially imported batches.
    return create_client(url,key).rpc('import_articoli_gtin_staging',{
        'p_rows':payload['rows'],'p_source_file':payload['source_file'],
        'p_source_version':payload['source_version'],'p_source_sha256':payload['source_sha256'],
        'p_discarded':len(payload['discarded'])}).execute().data


def main():
    import argparse
    parser=argparse.ArgumentParser(description='Valida il catalogo; non importa automaticamente online.')
    parser.add_argument('csv');parser.add_argument('--source-version',required=True)
    parser.add_argument('--payload',required=True)
    args=parser.parse_args()
    payload=prepare_catalog(args.csv,source_version=args.source_version)
    Path(args.payload).write_text(json.dumps(payload,ensure_ascii=False))
    print(json.dumps({k:v for k,v in payload.items() if k!='rows'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
