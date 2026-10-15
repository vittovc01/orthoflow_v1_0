"""Exact GS1 GTIN -> supplier REF. No fuzzy matching, no truth-derived mapping."""
import csv
import re
from pathlib import Path


def validate_gtin(value):
    from label_pipeline import gs1_parse
    return isinstance(value,str) and bool(re.fullmatch(r'\d{14}',value)) and not gs1_parse('(01)'+value).get('error')


def read_catalog(path):
    rows={}
    with Path(path).open(encoding='utf-8-sig',newline='') as f:
        r=csv.DictReader(f)
        if set(r.fieldnames or [])!={'gtin','ref','descrizione'}:raise ValueError('Colonne esatte richieste: gtin,ref,descrizione')
        for line,row in enumerate(r,2):
            gtin=row['gtin'].strip();ref=row['ref'].strip();description=row['descrizione'].strip()
            if not validate_gtin(gtin) or not ref or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9. /-]*',ref) or len(ref)>100:
                raise ValueError(f'GTIN/check digit o REF non valido alla riga {line}')
            record={'gtin':gtin,'ref':ref,'descrizione':description}
            if gtin in rows and rows[gtin]!=record:raise ValueError(f'GTIN duplicato discordante alla riga {line}')
            rows[gtin]=record
            if len(rows)>50000:raise ValueError('Massimo 50000 GTIN per importazione atomica')
    if not rows:raise ValueError('Catalogo vuoto')
    return rows


def supabase_lookup(client):
    cache={}
    def lookup(gtin):
        if gtin not in cache:
            rows=client.table('articoli_gtin').select('gtin,ref,descrizione').eq('gtin',gtin).limit(2).execute().data or []
            cache[gtin]=rows[0] if len(rows)==1 else None
        return cache[gtin]
    return lookup


def resolve_ref(item,lookup=None):
    from label_pipeline import gs1_parse
    row=dict(item)
    printed=[str(r['code']).strip() for r in row.get('ocr_reads',[]) if r.get('code')]
    if row.get('code'):printed.append(str(row['code']).strip())
    # Keep every OCR candidate, including rejected characters, for cross-check.
    printed+=list(row.get('local_ref_evidence',{}).get('candidates',[]))
    row['ref_ocr_observations']=list(dict.fromkeys(printed))
    decoded=[gs1_parse(b.get('raw','')) for b in row.get('barcodes',[])]
    gtins={b['gtin'] for b in decoded if not b.get('error') and b.get('gtin')}
    row['code']=None;row['catalog_ref_candidate']=None
    state='missing_gtin';record=None
    if len(gtins)==1:
        gtin=next(iter(gtins));row['gtin']=gtin
        state='catalogue_unavailable' if lookup is None else 'unknown_gtin'
        if lookup is not None:
            try:record=lookup(gtin) if callable(lookup) else lookup.get(gtin)
            except Exception:state='catalogue_unavailable'
        if record:
            # Never accept a response for a different key or an invalid mapping.
            if record.get('gtin')!=gtin or not str(record.get('ref') or '').strip():state='catalogue_unavailable'
            else:
                ref=record['ref'];row['catalog_ref_candidate']=ref
                if printed and any(p!=ref for p in printed):state='conflict'
                else:
                    row['code']=ref
                    row['catalog_description']=record.get('descrizione')
                    state='matched' if printed else 'ocr_missing'
    elif len(gtins)>1:state='conflict'
    row['catalog_resolution']=state
    messages={'missing_gtin':'REF da verificare: GTIN GS1 non decodificato',
      'unknown_gtin':'REF da verificare: GTIN assente in articoli_gtin',
      'catalogue_unavailable':'REF da verificare: catalogo GTIN non disponibile',
      'conflict':'REF discordante tra catalogo GTIN e OCR: nessuna sostituzione automatica',
      'ocr_missing':'REF da catalogo GTIN; controllo OCR non leggibile: da verificare'}
    if state!='matched':row['warning']=' · '.join(filter(None,[row.get('warning'),messages[state]]))
    return row
