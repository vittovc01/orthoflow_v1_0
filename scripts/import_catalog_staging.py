#!/usr/bin/env python3
"""Dry-run by default; one atomic RPC on an explicitly allowlisted staging ref."""
import argparse,csv,json,os,sys,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from supplier_catalog import load_supplier
PRODUCTION_REF='foawqtscqtwhpkbfbibj'

def staging_url(url,ref):
    if not ref or ref==PRODUCTION_REF or url!=f'https://{ref}.supabase.co':
        raise ValueError('Destinazione staging non valida; produzione vietata')
    return url

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('catalogo');p.add_argument('--out',type=Path,required=True);p.add_argument('--apply',action='store_true')
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    try:
        rows,report,rejected=load_supplier(a.catalogo)
        if not rows:raise ValueError('Nessuna riga valida')
        for name,data,fields in [('catalogo_completo.csv',rows,['gtin','ref','descrizione','categoria','fonte']),('scartate.csv',rejected,['riga','gtin','motivo'])]:
            with (a.out/name).open('w',newline='',encoding='utf-8') as f:
                w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(data)
        report.update(modalita='dry_run',nuove=None,aggiornate=None,invariate=None)
        if a.apply:
            url=staging_url(os.environ['OCR_STAGING_SUPABASE_URL'].rstrip('/'),os.environ['OCR_STAGING_PROJECT_REF'])
            key=os.environ['OCR_STAGING_SERVICE_KEY']
            req=urllib.request.Request(url+'/rest/v1/rpc/import_articoli_gtin_v2',data=json.dumps({'p_rows':rows}).encode(),
                headers={'apikey':key,'Authorization':'Bearer '+key,'Content-Type':'application/json'})
            with urllib.request.urlopen(req,timeout=180) as response:report.update(json.load(response))
            report['modalita']='staging'
        (a.out/'import_report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report));return 0
    except Exception as e:
        # Conflicts identify GTINs only. HTTP errors/credentials must never enter logs.
        from supplier_catalog import CatalogConflict
        print(str(e) if isinstance(e,CatalogConflict) else 'Importazione interrotta: '+type(e).__name__)
        (a.out/'import_report.json').write_text(json.dumps({'status':'failed','tipo':type(e).__name__,'conflitto':str(e) if isinstance(e,CatalogConflict) else None}))
        return 2
if __name__=='__main__':raise SystemExit(main())
