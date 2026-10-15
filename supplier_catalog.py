"""Supplier catalogue ingestion. GTINs are identifiers, never floating-point IDs."""
import csv,re
from collections import defaultdict
from pathlib import Path
from gtin_catalog import validate_gtin

class CatalogConflict(ValueError):
    pass

def normalize_records(records):
    grouped=defaultdict(list);rejected=[]
    records=[{k:str(v or '').strip() for k,v in r.items()} for r in records]
    raw_refs=defaultdict(set)
    for r in records:
        if validate_gtin(r.get('gtin','')) and r.get('ref'):raw_refs[r['gtin']].add(r['ref'])
    conflicts={g:sorted(refs) for g,refs in raw_refs.items() if len(refs)>1}
    if conflicts:raise CatalogConflict('GTIN con REF diversi: '+str(conflicts))
    for number,r in enumerate(records,2):
        r={k:str(v or '').strip() for k,v in r.items()}
        if not validate_gtin(r.get('gtin','')) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9. /-]{0,99}',r.get('ref','')):
            rejected.append({'riga':number,'gtin':r.get('gtin',''),'motivo':'GTIN/checksum o REF non valido'});continue
        if not r.get('fonte') or not r.get('categoria'):
            rejected.append({'riga':number,'gtin':r['gtin'],'motivo':'Fonte o categoria assente'});continue
        grouped[r['gtin']].append(r)
    conflicts={g:sorted({r['ref'] for r in rs}) for g,rs in grouped.items() if len({r['ref'] for r in rs})>1}
    if conflicts:raise CatalogConflict('GTIN con REF diversi: '+str(conflicts))
    rows=[]
    for g,rs in sorted(grouped.items()):
        descriptions={r.get('descrizione','') for r in rs}
        if len(descriptions)>1:raise CatalogConflict('Descrizioni discordanti per GTIN '+g)
        rows.append({'gtin':g,'ref':rs[0]['ref'],'descrizione':rs[0].get('descrizione',''),
          'categoria':' | '.join(sorted({r['categoria'] for r in rs})),
          'fonte':' | '.join(sorted({r['fonte'] for r in rs}))})
    return rows,{'scartate':len(rejected),'duplicate_identiche_o_stesso_ref':sum(len(v)-1 for v in grouped.values()),'valide_distinte':len(rows)},rejected

def load_supplier(path):
    path=Path(path)
    if path.suffix.lower()=='.xls':
        import xlrd
        sheet=xlrd.open_workbook(str(path)).sheet_by_index(0)
        if sheet.row_values(7)[:4]!=['Codice prodotto:','GTIN unità di spedizione','GTIN unità','Descrizione']:
            raise ValueError('Intestazioni catalogo J&J inattese')
        version=str(sheet.cell_value(0,1)).strip();records=[]
        for i in range(8,sheet.nrows):
            r=sheet.row_values(i)
            for c,kind in [(1,'GTIN spedizione'),(2,'GTIN unità')]:
                g=str(r[c]).strip()
                if not g:continue
                if sheet.cell_type(i,c)!=xlrd.XL_CELL_TEXT:
                    raise ValueError('GTIN numerico nel file originale: perdita di zeri possibile')
                records.append(dict(gtin=g,ref=r[0],descrizione=r[3],
                  categoria=' / '.join(str(v).strip() or '(non specificata)' for v in r[4:7]),
                  fonte=f'{path.name}; versione={version}; {kind}; stato={r[8]}'))
    else:
        with path.open(encoding='utf-8-sig',newline='') as f:
            reader=csv.DictReader(f)
            if not {'gtin','ref','descrizione','categoria','fonte'}<=set(reader.fieldnames or []):
                raise ValueError('Richieste colonne gtin,ref,descrizione,categoria,fonte')
            records=list(reader)
    return normalize_records(records)
