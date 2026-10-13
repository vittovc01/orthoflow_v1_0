from label_pipeline import verify_ref_evidence, reconcile


def test_partial_local_ref_does_not_discard_complete_ai_observation():
    row = verify_ref_evidence({'code': '04.211.016S', 'is_sterile': True},
                             {'status': 'read', 'candidates': ['211.016S']})
    assert row['code'] == '04.211.016S'
    assert 'parziale' in row['warning']


def test_partial_evidence_never_supplies_a_missing_prefix():
    row = verify_ref_evidence({'code': None},
                             {'status': 'read', 'candidates': ['211.016S']})
    assert row['code'] is None


def test_complete_disagreeing_refs_remain_blocked():
    row = verify_ref_evidence({'code': '04.211.016S', 'is_sterile': True},
                             {'status': 'read', 'candidates': ['04.211.018S']})
    assert row['code'] is None


def test_conflicting_lot_and_expiry_are_cleared_with_both_evidences_retained():
    barcode = {'gtin': '07611819425255', 'lot': '425L664', 'expiry': '2035-08-01'}
    row = reconcile({'code': '04.211.018S', 'lot': '4251664', 'expiry': '2035-06-01'}, [barcode])
    assert row['lot'] is None and row['expiry'] is None
    assert row['lot_ocr_original'] == '4251664'
    assert row['expiry_ocr_original'] == '2035-06-01'
    assert row['barcodes'] == [barcode]
    assert 'Conflitto OCR/GS1' in row['warning']
    assert row['reviewed'] is False


def test_agreeing_gs1_values_and_literal_ts_are_preserved():
    row = reconcile({'code': '04.211.018TS', 'lot': '372L595', 'expiry': '2030-02-01'},
                    [{'lot': '372L595', 'expiry': '2030-02-01'}])
    assert row['code'] == '04.211.018TS'
    assert row['lot'] == '372L595'
    assert row['expiry'] == '2030-02-01'


def test_repeated_same_barcode_cannot_refill_a_conflicting_field():
    barcode = {'lot': '425L664', 'expiry': '2035-08-01'}
    row = reconcile({'code': '04.211.018S', 'lot': '4251664', 'expiry': '2035-06-01'},
                    [barcode, dict(barcode)])
    assert row['lot'] is None and row['expiry'] is None
