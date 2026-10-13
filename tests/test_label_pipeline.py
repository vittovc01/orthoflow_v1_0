import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from label_pipeline import (aggregate_labels, unique_regions, review_errors,
    inventory_errors, gs1_parse, reconcile, decode_barcodes, analyze_labels)


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


def test_pipeline_keeps_failed_reads_and_deduplicates_geometry(tmp_path):
    path=tmp_path/'photo.png';Image.new('RGB',(100,100),'white').save(path)
    replies=iter([{'labels':[{'bbox':[1,1,400,400],'rotation':180},{'bbox':[2,2,401,401],'rotation':180},{'bbox':[500,500,999,999],'rotation':90}],'warning':None}, {'code':'REF','lot':'A','expiry':'2035-01-01','warning':None}])
    def create(**kwargs):
        try:return next(replies)
        except StopIteration:raise RuntimeError('OCR unavailable')
    client=SimpleNamespace(responses=SimpleNamespace(create=create))
    result=analyze_labels(path,client,'fake',{'properties':{'code':{},'lot':{},'expiry':{}}},lambda r:r)
    assert result['physical_label_count']==2
    assert result['items'][0]['rotation']==180
    assert result['items'][1]['code'] is None and 'fallita' in result['items'][1]['warning']
    assert not result['count_verified']
