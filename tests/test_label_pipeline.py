import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from label_pipeline import (aggregate_labels, unique_regions, review_errors,
    inventory_errors, gs1_parse, reconcile, decode_barcodes, analyze_labels,
    compare_reads, prepare_crop, local_ref_evidence, verify_ref_evidence)


def local_approval(path,regions,monkeypatch):
    import hashlib
    record={'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'approved':True,'labels_only_confirmed':True,'regions':regions}
    monkeypatch.setattr('local_label_reader.prepare_document',lambda _: record)
    return record


@pytest.mark.parametrize('size', [(538,183), (539,184), (540,185)])
def test_resampled_philos_symbol_preserves_exact_gs1_date(size):
    path = Path(__file__).parent / 'fixtures' / 'santa_lucia' / '04.png'
    with Image.open(path) as image:
        decoded = decode_barcodes(image.resize(size, Image.Resampling.LANCZOS))
    assert len(decoded) == 1
    assert decoded[0]['lot'] == '78864P9'
    assert decoded[0]['expiry'] == '2035-09-01'


@pytest.mark.parametrize('code', ['402.886', '402.8865', '04.211.018', '04.211.0185'])
def test_sterile_ref_suffix_is_not_invented(code):
    result = verify_ref_evidence(dict(code=code, is_sterile=True),
                                 {'status':'read','candidates':[code]})
    assert result['code'] is None
    assert result['ref_original'] == code
    r = row(); r.update(codice=code, is_sterile=True)
    assert review_errors([r], ['one'], 1, True)


@pytest.mark.parametrize('code', ['04.211.018S', '04.211.018TS'])
def test_literal_suffix_evidence_is_preserved(code):
    result = verify_ref_evidence(dict(code=code, is_sterile=True),
                                 {'status':'read','candidates':[code]})
    assert result['code'] == code
    assert not result['warning']


def test_local_read_disagreement_cannot_repair_ai_ref():
    result = verify_ref_evidence(dict(code='402.886S', is_sterile=True),
                                 {'status':'read','candidates':['402.8865']})
    assert result['code'] is None


def test_lot_in_ref_column_is_rejected():
    result = verify_ref_evidence(dict(code='LOT',lot='LOT'),
                                 {'status':'unreadable','candidates':[]})
    assert result['code'] is None


def test_local_ocr_missing_binary_keeps_explicit_warning(monkeypatch):
    monkeypatch.setattr('label_pipeline.shutil.which', lambda _: None)
    evidence = local_ref_evidence(Image.new('RGB',(20,20)))
    assert evidence['status']=='unavailable'
    result = verify_ref_evidence(dict(code='402.886S'), evidence)
    assert result['code']=='402.886S' and result['warning']


def test_local_ocr_timeout_does_not_abort_label(monkeypatch):
    import subprocess
    monkeypatch.setattr('label_pipeline.shutil.which', lambda _: '/usr/bin/tesseract')
    def timeout(*args, **kwargs):
        assert kwargs['timeout']==15 and isinstance(kwargs['input'], bytes)
        raise subprocess.TimeoutExpired('tesseract',15)
    monkeypatch.setattr('label_pipeline.subprocess.run', timeout)
    assert local_ref_evidence(Image.new('RGB',(20,20)))['status']=='unavailable'


@pytest.mark.parametrize('wrong',['04.211.085S','04.211.005S','4.211.018S','04.211.018TS'])
def test_ref_disagreement_never_uses_description(wrong):
    result = compare_reads(dict(code='04.211.018S',lot='LOT',expiry='2035-01-01'),
                           dict(code=wrong,lot='LOT',expiry='2035-01-01'))
    assert result['code'] is None
    assert result['ocr_reads'][0]['code']=='04.211.018S'
    assert result['warning']


def test_mixed_barcode_crop_cannot_supply_identity():
    result = reconcile(dict(code='04.211.018S',lot='A',expiry='2035-01-01'),
                       [dict(gtin='G1',lot='A'),dict(gtin='G2',lot='B')])
    assert result['code'] is None and result['lot'] is None
    assert 'Più identità' in result['warning']


def test_preprocessing_preserves_source_and_bounds():
    source = Image.new('RGB',(300,100),'white')
    assert prepare_crop(source).size == (900,300)
    assert source.size == (300,100)



def row(label='one', lot='LOT'):
    return dict(label_id=label,codice='413.040S',lotto=lot,scadenza='2035-04-01',quantita=1,verificata=True)


@pytest.mark.parametrize('n',[2,3])
def test_physical_duplicates(n):
    output=aggregate_labels([row(str(i)) for i in range(n)])
    assert len(output)==1 and output[0]['quantita']==n


def test_same_ref_different_lots():
    assert len(aggregate_labels([row('1','A'),row('2','B')]))==2


def test_artificial_duplicate_observation_rejected():
    with pytest.raises(ValueError):
        aggregate_labels([row(),row()])


def test_overlap_removed_before_identity():
    boxes=[dict(page=1,bbox=[10,10,100,100]),dict(page=1,bbox=[11,11,101,101]),dict(page=1,bbox=[110,10,200,100])]
    assert len(unique_regions(boxes))==2
    assert len(unique_regions([boxes[0],dict(boxes[0],page=2)]))==2


@pytest.mark.parametrize('value',['413.?40S','07611819268623',''])
def test_incomplete_ref_blocks(value):
    r=row();r['codice']=value
    assert review_errors([r],['one'],1,True)


@pytest.mark.parametrize('quantity',[0,2,-1,float('nan'),float('inf')])
def test_quantity_is_one_per_label(quantity):
    r=row();r['quantita']=quantity
    assert review_errors([r],['one'],1,True)


def test_review_and_count_blocks():
    assert review_errors([row()],['one'],16,True)
    assert review_errors([row()],['one'],1,False)
    r=row();r['verificata']=False
    assert review_errors([r],['one'],1,True)
    assert not review_errors([row()],['one'],1,True)


def test_inventory_preserves_suffix_lot_expiry():
    stock=[dict(codice='413040S',lotto='LOT',scadenza='2035-04-01',quantita=2)]
    assert not inventory_errors([row('1'),row('2')],stock)
    assert inventory_errors([row('1'),row('2'),row('3')],stock)
    assert inventory_errors([row('1','OTHER')],stock)
    stock[0]['scadenza']=None
    assert inventory_errors([row()],stock)
    stock[0]['codice']='413040'
    assert inventory_errors([row()],stock)


def test_gs1_separates_gtin_ref_and_detects_conflict():
    decoded=gs1_parse('01076118192686232015173504011062405P5')
    assert decoded['lot']=='62405P5' and decoded['expiry']=='2035-04-01'
    r=reconcile(dict(code=decoded['gtin'],lot='WRONG',expiry=None),[decoded])
    assert r['code'] is None and 'Conflitto' in r['warning']
    assert 'error' in gs1_parse('0107611')
    assert 'error' in gs1_parse('(01)07611819268624(17)350401(10)ABC')


FIXTURE=Path(__file__).parent/'fixtures'/'santa_lucia'
MANIFEST=json.loads((FIXTURE/'manifest.json').read_text())


@pytest.mark.parametrize('label',MANIFEST['labels'],ids=lambda r:r['label_id'])
def test_santa_lucia_individual_gs1_and_upside_down(label):
    # Independent reference annotations, NOT automatic detector results.
    image=Image.open(FIXTURE/f"{int(label['label_id'].split(':')[-1]):02}.png")
    decoded=decode_barcodes(image)
    inverted=decode_barcodes(image.rotate(180))
    assert [(b.get('lot'),b.get('expiry')) for b in decoded]==[(b.get('lot'),b.get('expiry')) for b in inverted]
    if not decoded:
        assert label['label_id']=='santa:2'  # Explicit unreadable DataMatrix.
    for b in decoded:
        assert not b.get('error')
        assert b['lot']==label['lot'] and b['expiry']==label['expiry']


def test_santa_lucia_reference_quantities():
    rows=[dict(label_id=r['label_id'],codice=r['code'],lotto=r['lot'],scadenza=r['expiry'],quantita=1) for r in MANIFEST['labels']]
    grouped=aggregate_labels(rows)
    assert len(rows)==16 and len(grouped)==15
    assert sum(r['quantita'] for r in grouped)==16
    assert next(r for r in grouped if r['codice']=='292.720S')['quantita']==2


def test_pipeline_keeps_failed_reads_and_deduplicates_geometry(tmp_path,monkeypatch):
    path=tmp_path/'photo.png';Image.new('RGB',(100,100),'white').save(path)
    regions=[dict(page=1,bbox=[1,1,400,400],rotation=180),dict(page=1,bbox=[500,500,999,999],rotation=90)]
    approval=local_approval(path,regions,monkeypatch)
    replies=iter([{'code':'REF','lot':'A','expiry':'2035-01-01','warning':None}]*2)
    def create(**kwargs):
        assert kwargs['text']['format']['name'] in {'single_label','independent_label_read'}
        try:return next(replies)
        except StopIteration:raise RuntimeError('OCR unavailable')
    client=SimpleNamespace(responses=SimpleNamespace(create=create))
    result=analyze_labels(path,client,'fake',{'properties':{'code':{},'lot':{},'expiry':{}}},lambda r:r,privacy_approval=approval)
    assert result['physical_label_count']==2
    assert result['items'][0]['rotation']==180
    assert result['items'][1]['code'] is None and 'fallita' in result['items'][1]['warning']
    assert not result['count_verified']


def test_linear_detector_cannot_drop_a_faint_fourth_sticker():
    from label_pipeline import merge_linear_regions
    proposals = [dict(page=1, bbox=[10, y, 300, y+90], rotation=0)
                 for y in (10, 210, 410, 610)]
    local = [dict(bbox=r['bbox'], rotation=180) for r in proposals[:3]]
    result = merge_linear_regions(local, proposals, 1)
    assert len(result) == 4
    assert result[-1] == proposals[-1]
    assert all(r['rotation'] == 180 for r in result[:3])


def test_local_crop_spanning_two_labels_cannot_replace_either():
    from label_pipeline import merge_linear_regions
    proposals = [dict(page=1,bbox=b,rotation=0)
                 for b in ([0,0,200,100],[0,110,200,210])]
    assert merge_linear_regions([dict(bbox=[0,0,200,210],rotation=0)],proposals,1)==proposals


def test_unmatched_local_label_is_added_without_identity_deduplication():
    from label_pipeline import merge_linear_regions
    proposals = [dict(page=1,bbox=[0,0,200,100],rotation=0)]
    result=merge_linear_regions([dict(bbox=[0,200,200,300],rotation=0)],proposals,1)
    assert len(result)==2
    assert len(merge_linear_regions([dict(bbox=[0,0,200,100],rotation=0)],proposals,1))==1


def test_approved_local_crops_exclude_header_and_preserve_two_units(tmp_path, monkeypatch):
    path=tmp_path/'page.png'
    Image.new('RGB',(400,400),'white').save(path)
    monkeypatch.setattr('label_geometry.locate_datamatrix_labels', lambda _: [])
    monkeypatch.setattr('label_pipeline.decode_barcodes', lambda _: [])
    monkeypatch.setattr('label_pipeline.local_ref_evidence', lambda _: {'status':'unreadable','candidates':[]})
    corrected=[{'bbox':[100,400,900,600],'rotation':0},
               {'bbox':[100,650,900,850],'rotation':0}]
    approval=local_approval(path,[dict(r,page=1) for r in corrected],monkeypatch)
    read={'code':'413.040S','lot':'LOT','expiry':'2035-04-01'}
    def create(**kwargs):
        name=kwargs['text']['format']['name']
        assert name in {'single_label','independent_label_read'}
        return dict(read)
    result=analyze_labels(path,SimpleNamespace(responses=SimpleNamespace(create=create)),
                          'fake',{'properties':{'code':{},'lot':{},'expiry':{}}},lambda r:r,privacy_approval=approval)
    assert [r['bbox'] for r in result['items']]==[r['bbox'] for r in corrected]
    assert result['physical_label_count']==2
    assert len({r['label_id'] for r in result['items']})==2
    grouped=aggregate_labels([dict(label_id=r['label_id'],codice=r['code'],lotto=r['lot'],
                                   scadenza=r['expiry'],quantita=r['quantity']) for r in result['items']])
    assert len(grouped)==1 and grouped[0]['quantita']==2


def test_physical_sticker_edges_survive_ai_count_disagreement(tmp_path,monkeypatch):
    from label_geometry import locate_datamatrix_labels
    from label_pipeline import select_label_regions
    source=Image.open(Path(__file__).parent/'fixtures'/'synthes_mixed_angles'/'labels.png')
    local=locate_datamatrix_labels(source)
    # Simulate the visual detector finding only four of seven physical stickers.
    proposals=[dict(r,page=1) for r in local[:4]]
    assert len(select_label_regions(local,proposals,'synthes_datamatrix',1,source))==7


def test_header_proposal_cannot_add_quantity_to_measured_stickers(monkeypatch):
    from label_geometry import locate_datamatrix_labels
    from label_pipeline import select_label_regions
    source=Image.open(Path(__file__).parent/'fixtures'/'synthes_mixed_angles'/'labels.png')
    local=locate_datamatrix_labels(source)
    monkeypatch.setattr('label_pipeline.local_ref_evidence',lambda _: {'candidates':[]})
    monkeypatch.setattr('label_pipeline.decode_barcodes',lambda _: [])
    proposals=[dict(page=1,bbox=[700,900,900,990],rotation=0)]
    assert len(select_label_regions(local,proposals,'synthes_datamatrix',1,source))==7


@pytest.mark.parametrize('raw',[
    '(01)07611819268623(17)350401(10)'+'A'*21,
    '(01)07611819268623(99)UNKNOWN',
    '(01)07611819268623(20)X5',
    '(01)07611819268623(30)abc',
])
def test_parenthesized_gs1_validates_lengths_and_supported_ais(raw):
    assert 'error' in gs1_parse(raw)


def test_gs1_evidence_survives_ai_read_failure(tmp_path,monkeypatch):
    path=tmp_path/'barcode.png';Image.new('RGB',(100,100),'white').save(path)
    monkeypatch.setattr('label_geometry.locate_datamatrix_labels',lambda _: [])
    approval=local_approval(path,[dict(page=1,bbox=[10,10,900,900],rotation=0)],monkeypatch)
    barcode=gs1_parse('(01)07611819268623(17)350401(10)LOT')
    monkeypatch.setattr('label_pipeline.decode_barcodes',lambda _: [dict(raw='(01)07611819268623(17)350401(10)LOT',**barcode)])
    def create(**kwargs):
        name=kwargs['text']['format']['name']
        if name in ('physical_labels','audited_physical_labels'):
            return {'labels':[dict(bbox=[10,10,900,900],rotation=0)],'layout':'unknown','warning':None}
        raise RuntimeError('AI offline')
    result=analyze_labels(path,SimpleNamespace(responses=SimpleNamespace(create=create)),
                          'fake',{'properties':{'code':{},'lot':{},'expiry':{}}},lambda r:r,privacy_approval=approval)
    item=result['items'][0]
    assert item['code'] is None and item['lot']=='LOT' and item['expiry']=='2035-04-01'
    assert item['assessment']['fields']['lot']['method']=='datamatrix'
    assert item['gtin']=='07611819268623'


def test_printed_gtin_conflict_cannot_be_overwritten_by_datamatrix():
    result=reconcile({'code':'413.040S','gtin':'07611819268623','lot':'LOT','expiry':'2035-04-01'},
                     [{'gtin':'07611819425255','lot':'LOT','expiry':'2035-04-01'}])
    assert result['gtin'] is None
    assert result['gtin_ocr_original']=='07611819268623'
    assert 'Conflitto OCR/GS1: gtin' in result['warning']
