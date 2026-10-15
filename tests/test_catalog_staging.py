import pytest
from supplier_catalog import normalize_records,CatalogConflict
from gtin_catalog import resolve_ref,missing_gtins,missing_gtins_csv
from scripts.import_catalog_staging import staging_url

def row(ref='413.040S',**kw):
    return dict(gtin='07611819268623',ref=ref,descrizione='Vite',categoria='Trauma',fonte='catalog.xls; versione=2024',**kw)

def test_duplicate_and_conflict():
    rows,report,bad=normalize_records([row(),row()])
    assert len(rows)==1 and report['duplicate_identiche_o_stesso_ref']==1 and not bad
    with pytest.raises(CatalogConflict):normalize_records([row(),row('ALTRO')])

def test_multiple_gtins_same_ref_and_invalid_check_digit():
    r=row();r['gtin']='07611819268548'
    rows,report,_=normalize_records([row(),r,{**row(),'gtin':'07611819268624'}])
    assert len(rows)==2 and report['scartate']==1

def test_only_staging_is_allowed():
    for url,ref in [('https://foawqtscqtwhpkbfbibj.supabase.co','foawqtscqtwhpkbfbibj'),('https://evil.example','staging')]:
        with pytest.raises(ValueError):staging_url(url,ref)
    assert staging_url('https://staging.supabase.co','staging')

def test_unknown_gtin_export_and_printed_conflict():
    item={'code':'413.040S','barcodes':[{'raw':'(01)07611819268623'}]}
    unknown=resolve_ref(item,{})
    assert unknown['code'] is None
    assert missing_gtins([unknown,unknown])==[{'gtin':'07611819268623','occorrenze':2}]
    assert '413.040S' not in missing_gtins_csv([unknown])
    conflict=resolve_ref({**item,'code':'413.048S'},{'07611819268623':row()})
    assert conflict['catalog_resolution']=='conflict' and conflict['code'] is None


def test_conflicting_ref_must_stop_even_if_metadata_row_would_be_discarded():
    invalid={**row('ALTRO'),'fonte':''}
    with pytest.raises(CatalogConflict):normalize_records([row(),invalid])
