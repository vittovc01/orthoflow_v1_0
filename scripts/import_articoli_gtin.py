#!/usr/bin/env python3
"""Validate supplier CSV; --apply performs one atomic server RPC, no overwrites."""
import argparse
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gtin_catalog import read_catalog


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('csv');p.add_argument('--apply',action='store_true')
    a=p.parse_args()
    try:
        rows=read_catalog(a.csv)
        print('Catalogo valido:',len(rows),'GTIN distinti')
        if a.apply:
            from supabase import create_client
            client=create_client(os.environ['OCR_CATALOG_SUPABASE_URL'],os.environ['OCR_CATALOG_SERVICE_KEY'])
            n=client.rpc('import_articoli_gtin',{'p_rows':list(rows.values())}).execute().data
            print('Righe inserite:',n)
        else:print('Solo validazione: nessuna scrittura. Usare --apply per importare.')
        return 0
    except Exception as e:
        # No raw network error, credentials or request headers in logs.
        print('Importazione non completata:',type(e).__name__);return 2


if __name__=='__main__':raise SystemExit(main())
