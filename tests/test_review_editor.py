import math
from copy import deepcopy

import pytest
from label_pipeline import review_errors, aggregate_labels
from review_editor import (apply_review_edits, row_errors, catalogue_warning,
                           expected_label_count, count_warning, technical_gtin)


def row(label='one', **changes):
    return dict(label_id=label,codice='TEST-A',lotto='LOT-A',scadenza='2035-01-01',quantita=1,
                crop_data_url='private-product-crop',gtin=None,**changes)


@pytest.mark.parametrize('gtin',[None,'',float('nan'),'nan','NaN','<NA>','unreadable','00000000000017'])
def test_technical_gtin_never_blocks(gtin):
    item=row();item['gtin']=gtin
    assert not review_errors([item],['one'],1,True)
    assert catalogue_warning(item,{})=='TEST-A, lotto LOT-A: REF non confrontato con il catalogo'
    if gtin is None or str(gtin).lower() in {'','nan','<na>'}:assert technical_gtin(gtin) is None


def test_manual_edit_preserves_evidence_and_logs_before_after_actor_time():
    original=row();snapshot=deepcopy(original)
    edits=[dict(original,codice='TEST-B',lotto='LOT-B',scadenza='2036-03-01',quantita=2,gtin='forged')]
    result,logs=apply_review_edits([original],edits,actor='agent',timestamp='2026-10-16T10:00:00+00:00')
    assert original==snapshot
    assert result[0]['gtin'] is None and result[0]['crop_data_url']==original['crop_data_url']
    assert result[0]['quantita']==2 and not row_errors(result[0])
    changes={entry['field']:entry for entry in logs}
    assert changes['codice']['original']=='TEST-A' and changes['codice']['corrected']=='TEST-B'
    assert set(changes)=={'codice','lotto','scadenza','quantita'}
    assert all(l['method']=='manuale' and l['user']=='agent' and l['timestamp']=='2026-10-16T10:00:00+00:00' for l in logs)
    assert catalogue_warning(result[0],{'00000000000017':'OTHER'}).endswith('REF digitato non presente nel catalogo')
    assert apply_review_edits(result,result,actor='agent')[1]==[], 'reruns must not duplicate audit entries'


def test_add_delete_and_prefilled_count_preserve_trace():
    original=row();other=row('two');other['lotto']='LOT-B'
    added=dict(codice='TEST-C',lotto='LOT-C',scadenza='2037-01-01',quantita=3)
    rows,log=apply_review_edits([original,other],[original,added],actor='operator')
    assert len(rows)==2 and rows[1]['manual_entry'] and rows[1]['label_id'].startswith('manual:')
    assert rows[1]['crop_data_url'] is None and rows[1]['gtin'] is None
    assert any(l['operation']=='delete' and l['original']['lotto']=='LOT-B' for l in log)
    assert any(l['operation']=='add' for l in log)
    assert expected_label_count(rows)==2
    assert count_warning(rows,3).endswith('Controlla le righe aggiunte, eliminate o ripetute.')
    assert 'differenza +1' in count_warning(rows,3)
    assert not review_errors(rows,[r['label_id'] for r in rows],3,True), 'count mismatch is advisory'
    assert sum(r['quantita'] for r in aggregate_labels(rows))==4


def test_missing_fields_are_attributed_to_ref_and_lot_only_bad_row_is_marked():
    valid=row();bad=row('bad');bad.update(codice='TEST-B',lotto='LOT-B',scadenza=float('nan'),quantita=0)
    errors=review_errors([valid,bad],['one','bad'],2,True)
    assert errors==['TEST-B, lotto LOT-B: scadenza mancante','TEST-B, lotto LOT-B: quantità non valida: inserire un intero maggiore di zero']
    assert not row_errors(valid) and all('nan' not in e for e in errors)


@pytest.mark.parametrize('quantity',[0,-1,1.5,float('nan'),float('inf'),True,None,''])
def test_invalid_quantities_remain_invalid(quantity):
    item=row();item['quantita']=quantity
    assert any('quantità non valida' in e for e in row_errors(item))


def test_unknown_id_and_duplicate_id_cannot_forge_provenance():
    with pytest.raises(ValueError):apply_review_edits([row()],[row('invented')],actor='agent')
    with pytest.raises(ValueError):apply_review_edits([row()],[row(),row()],actor='agent')


def test_catalogue_supplies_ref_from_decoded_gtin_without_overwriting_manual_input():
    from ocr_review import build_review
    item={'label_id':'one','code':None,'gtin':'00000000000017','lot':'LOT-A','expiry':'2035-01-01','quantity':1}
    catalog={'00000000000017':'TEST-A'}
    result=build_review({'items':[item]},catalog=catalog)['items'][0]
    assert result['code']=='TEST-A' and result['ref_source']=='articoli_gtin'
    assert item['code'] is None
    manual=dict(item,code='TEST-B',manual_fields=['code'])
    assert build_review({'items':[manual]},catalog=catalog)['items'][0]['code']=='TEST-B'
    cleared=dict(item,manual_fields=['code'])
    assert build_review({'items':[cleared]},catalog=catalog)['items'][0]['code'] is None


def test_calendar_date_is_normalized_before_sending_to_postgres():
    rows,_=apply_review_edits([row()],[dict(row(),scadenza='13/02/2036')],actor='operator')
    assert rows[0]['scadenza']=='2036-02-13' and not row_errors(rows[0])


def test_empty_dataframe_flags_cannot_silently_exclude_an_invalid_row():
    item=row();item.update(escludi_riga=float('nan'),scadenza='')
    assert expected_label_count([item])==1
    assert row_errors(item)==['TEST-A, lotto LOT-A: scadenza mancante']


@pytest.mark.parametrize('raw,expected',[
    ('REF 3095-040','3095-040'),('ref:1504-00-204','1504-00-204'),
    (' REF\u00a0413.016S ', '413.016S'),('REF 413.016TS','413.016TS'),
    ('REFERENCE-A','REFERENCE-A'),('REF123','REF123'),('413.016S','413.016S'),
])
def test_printed_ref_marker_is_not_product_identity(raw, expected):
    from review_editor import product_ref, canonical_values
    from ocr_review import exact_code
    assert product_ref(raw) == expected
    assert canonical_values({'code':raw})['codice'] == expected
    assert exact_code(raw) == exact_code(expected)
