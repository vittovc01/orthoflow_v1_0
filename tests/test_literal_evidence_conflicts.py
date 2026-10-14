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


def test_depuy_sterile_refs_do_not_require_a_synthes_suffix():
    from label_pipeline import review_errors
    for code in ('4515-70-006', '4515-70-011', '4515-70-000', '4515-70-005', '3095-040', '1506-70-007', '1504-00-206', '1520-20-606'):
        result=verify_ref_evidence({'code':code,'is_sterile':True}, {'status':'unreadable','candidates':[]})
        assert result['code']==code
        row={'label_id':'one','codice':code,'is_sterile':True,'lotto':'LOT','scadenza':'2036-05-31','quantita':1,'verificata':True}
        assert not review_errors([row],['one'],1,True)


def test_synthes_geometry_never_crops_a_depuy_or_mixed_layout():
    from label_pipeline import select_label_regions
    local=[{'bbox':[5,5,50,50],'rotation':0,'geometry_source':'local'}]
    proposals=[{'bbox':[0,0,200,100],'rotation':0}]
    for layout in ('other','mixed','unknown',None):
        assert select_label_regions(local,proposals,layout,1)==proposals
    assert select_label_regions(local,proposals,'synthes_datamatrix',1)==proposals


def test_local_geometry_requires_complete_one_to_one_corroboration():
    from label_pipeline import select_label_regions
    local=[{'bbox':[0,0,100,100],'rotation':180,'geometry_source':'local'}]
    same=[{'bbox':[5,5,95,95],'rotation':0}]
    assert select_label_regions(local,same,'synthes_datamatrix',1)[0]['rotation']==180
    missing=same+[{'bbox':[200,200,300,300],'rotation':0}]
    assert select_label_regions(local,missing,'synthes_datamatrix',1)==missing


def test_generic_casa_di_cura_does_not_capture_malzoni_header():
    from clinic_matching import clinic_default_index
    clients=[{'descrizione':'CARDIOMED SPA'}, {'descrizione':'CASA DI CURA'}, {'descrizione':'CASA DI CURA PRIVATA MALZONI'}]
    assert clinic_default_index('Casa di Cura Malzoni',clients)==2
    assert clinic_default_index('Casa di Cura',clients)==1
    assert clinic_default_index('Casa di Cura non identificata',clients)==0


def test_depuy_linear_fixtures_exclude_inventory_tags_and_keep_every_piece():
    from pathlib import Path
    from PIL import Image
    from linear_label_geometry import locate_linear_labels
    fixture=Path(__file__).parent/'fixtures'/'depuy_linear'
    for name,count in [('velys.jpg',6),('attune.jpg',5),('atripalda.jpg',4)]:
        image=Image.open(fixture/name)
        for angle in (0,90,180,270):
            regions=locate_linear_labels(image.rotate(angle,expand=True))
            assert len(regions)==count, (name,angle,regions)
            assert all(r['geometry_source']=='local_linear_barcodes' for r in regions)


def test_long_lived_session_refreshes_stale_ocr_version():
    import label_pipeline
    import ocr_runtime
    expected=label_pipeline.PIPELINE_VERSION
    label_pipeline.PIPELINE_VERSION='stale-session-version'
    ocr_runtime._signatures.clear()
    try:
        assert ocr_runtime.current_label_pipeline().PIPELINE_VERSION==expected
    finally:
        label_pipeline.PIPELINE_VERSION=expected


def test_scanned_atripalda_crops_include_full_printed_headers():
    from pathlib import Path
    from PIL import Image
    from linear_label_geometry import locate_linear_labels
    image=Image.open(Path(__file__).parent/'fixtures'/'depuy_linear'/'atripalda.jpg')
    regions=locate_linear_labels(image)
    headers=[(140,851,565,878),(590,857,1020,890),
             (125,1090,590,1145),(650,1100,1115,1137)]
    for left,top,right,bottom in headers:
        containing=[r for r in regions if r['bbox'][0]*image.width/1000<=left
                    and r['bbox'][1]*image.height/1000<=top
                    and r['bbox'][2]*image.width/1000>=right
                    and r['bbox'][3]*image.height/1000>=bottom]
        assert len(containing)==1, (headers,regions)


def test_ref_geometry_uses_single_hyphen_and_partial_ref_but_not_dates_or_footer():
    from linear_label_geometry import _ref_marker
    for text in ('3095-040','1504-00-','4515-70-006','04.112.622S'):
        assert _ref_marker({'text':text})
    for text in ('2036-07-31','2036-071','PAT3095-040','000-02'):
        assert not _ref_marker({'text':text})
