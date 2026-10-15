"""Scoring tests use injected observations, never claim real-model accuracy."""
from copy import deepcopy
from io import BytesIO
import json
import pytest
from PIL import Image, ImageFilter, ImageEnhance
from evaluate_ocr import evaluate_case, match_labels, condition_flag, evaluate
from ocr_review import aggregate_review, mark_cross_photo_candidates, verified_physical_count
from ocr_service import analyze_documents
from ocr_repository import OriginalDocument
from image_quality import inspect_quality


def truth(**kw):
    return dict(file='a.png',truth_index=0,code='REF1',lot='LOT1',expiry='2030-01-01',
                physical_id='unit1',case_id='case1',bbox=[0,0,500,500],page=1,conditions=[],**kw)


def item(**kw):
    r=dict(label_id='one',code='REF1',lot='LOT1',expiry='2030-01-01',bbox=[0,0,500,500],page=1,
           assessment={'fields':{k:{'status':'agreement','method':'datamatrix+ocr'} for k in ('code','lot','expiry')}})
    r.update(kw);return r


def score(observed, expected=None):
    return evaluate_case('case1',{'a.png':expected or [truth()]},{'items':observed},1)


def test_spatial_match_does_not_hide_wrong_identifier():
    rows,counts,fields=score([item(code='WRONG')])
    assert counts['matched']==1 and counts['silent_errors']==1 and fields['ref']['silent']==1
    assert next(r for r in rows if r.get('field')=='ref')['problem']=='errore_silenzioso'


def test_generic_review_is_not_a_field_warning():
    assert score([item(code='WRONG',review_required=True)])[1]['silent_errors']==1
    r=item(code='WRONG');r['assessment']['fields']['code']['status']='conflict'
    assert score([r])[1]['silent_errors']==0


def test_extra_safe_label_is_a_silent_error():
    rows,counts,fields=score([item(),item(label_id='extra',bbox=[600,600,900,900])])
    assert counts['extra']==1 and counts['silent_errors']==3
    assert all(v['silent']==1 for v in fields.values())


def test_boxes_take_priority_over_identical_batch_fields():
    a=truth();b=deepcopy(a);b.update(physical_id='unit2',bbox=[500,500,1000,1000])
    pairs,missing,extra=match_labels([a,b],[item(bbox=b['bbox']),item(bbox=a['bbox'])])
    assert set(pairs)=={(0,1),(1,0)} and not missing and not extra


def test_quantity_wrong_despite_correct_fields():
    a=truth();b=deepcopy(a);b.update(physical_id='unit2',bbox=[500,500,1000,1000])
    assert score([item()],[a,b])[1]['quantity_wrong']==1


def test_same_photo_same_batch_is_two_units():
    assert aggregate_review([item(),item(label_id='two')])[0]['quantity']==2


def test_cross_photo_never_automatically_counts_two():
    rows=[item(document_index=0),item(label_id='two',document_index=1)]
    mark_cross_photo_candidates(rows)
    with pytest.raises(ValueError,match='Identità fisica incerta'):aggregate_review(rows)
    for r in rows:r.update(verificata=True,physical_distinct_confirmed=True)
    assert aggregate_review(rows)[0]['quantity']==2
    rows[1]['duplicate_of']='one'
    assert verified_physical_count(rows)==1 and aggregate_review(rows)[0]['quantity']==1
    rows[0]['duplicate_of']='two'
    with pytest.raises(ValueError):verified_physical_count(rows)


def test_exact_photo_copy_not_reanalyzed_or_counted_twice():
    data=BytesIO();Image.new('RGB',(30,30),'white').save(data,format='PNG');calls=[]
    def reader(*a,**kw):calls.append(1);return {'items':[item()]}
    r=analyze_documents([OriginalDocument('a.png',data.getvalue()),OriginalDocument('b.png',data.getvalue())],analyzer=reader)
    assert len(calls)==1 and len(r['items'])==1 and r['documents'][1]['status']=='duplicate'


@pytest.mark.parametrize('condition,warning',[
 ('overlap','etichette sovrapposte'),('touching','confini delle etichette incerti'),
 ('clipped','etichetta tagliata al bordo'),('skew','etichetta inclinata'),
 ('glare','possibile riflesso'),('dark','bassa luminosità'),('blur','foto sfocata'),
 ('barcode_unreadable','DataMatrix non leggibile'),('text_unreadable','testo non letto'),
 ('barcode_text_conflict','dati discordanti')])
def test_difficult_conditions_need_specific_alert(condition,warning):
    assert not condition_flag(item(),condition,[])
    assert condition_flag(item(warning=warning),condition,[])


def test_actual_quality_on_dark_and_blurred_fixture():
    p='tests/fixtures/santa_lucia/01.png'
    original=Image.open(p).convert('RGB')
    assert 'dark' in inspect_quality(ImageEnhance.Brightness(original).enhance(.12))['conditions']
    assert 'blur' in inspect_quality(original.filter(ImageFilter.GaussianBlur(8)))['conditions']


def test_live_without_key_is_not_measured(tmp_path,monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    Image.new('RGB',(20,20)).save(tmp_path/'a.png')
    gt=tmp_path/'truth.csv';gt.write_text('file,ref,lotto,scadenza,quantita\na.png,REF1,LOT1,2030-01-01,1\n')
    r=evaluate(tmp_path,gt,tmp_path/'out',mode='live')
    assert not r['accepted'] and r['silent_errors'] is None and r['status']=='NOT_RUN'
    assert 'NON_MISURATI' in (tmp_path/'out/report.csv').read_text(encoding='utf-8-sig')


def test_tesseract_literal_quote_cannot_consume_later_tsv_rows(monkeypatch):
    from types import SimpleNamespace
    from label_pipeline import local_ref_evidence
    import label_pipeline
    monkeypatch.setattr(label_pipeline.shutil,'which',lambda _: '/usr/bin/tesseract')
    raw=b'level\tconf\ttext\n5\t90\t"\n5\t99\t04.200.016S\n'
    monkeypatch.setattr(label_pipeline.subprocess,'run',lambda *a,**kw: SimpleNamespace(stdout=raw))
    assert local_ref_evidence(Image.new('RGB',(20,10)))['candidates']==['04.200.016S']


@pytest.mark.parametrize('regions,expected',[
 ([{'bbox':[0,0,500,300]},{'bbox':[450,0,950,300]}],None),
 ([{'bbox':[0,0,500,300]},{'bbox':[350,0,950,300]}],'sovrapposte'),
 ([{'bbox':[0,0,500,300]},{'bbox':[500,0,950,300]}],'toccano'),
 ([{'bbox':[0,0,500,300],'deskew_angle':12}],'inclinata')])
def test_measured_geometry_alerts(regions,expected):
    from image_quality import geometry_alerts
    messages=geometry_alerts(regions)
    assert any(expected in m for m in messages) if expected else not messages


def test_clipped_label_assessment_requests_new_photo():
    from ocr_review import assess_label
    assert any('bordo' in s for s in assess_label(item(bbox=[0,50,500,800]))['issues'])


def test_real_quality_glare_patch():
    from PIL import ImageDraw
    img=Image.new('RGB',(512,256),(100,100,100));ImageDraw.Draw(img).rectangle([180,30,300,180],fill='white')
    assert 'glare' in inspect_quality(img)['conditions']


def test_production_preflight_cannot_accept_local_or_reduced_thresholds(tmp_path):
    import subprocess,sys
    evidence=tmp_path/'summary.json';evidence.write_text(json.dumps({'accepted':False}))
    command=[sys.executable,'-O','scripts/check_ocr_acceptance.py',str(evidence),'--pipeline-sha256','hash']
    result=subprocess.run(command,capture_output=True,text=True)
    assert result.returncode==2 and 'BLOCKED' in result.stdout
