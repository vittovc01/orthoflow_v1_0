from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import base64,hashlib,json,subprocess,sys
import pytest
from PIL import Image,ImageDraw
from gtin_catalog import read_catalog,resolve_ref
from ocr_review import assess_label
from label_pipeline import analyze_labels
from safe_ocr_logs import redact

GTIN='07611819268623'
CAT={GTIN:{'gtin':GTIN,'ref':'413.040S','descrizione':'Vite'}}


def observation(code='413.040S'):
    return dict(code=code,lot='LOT',expiry='2035-04-01',barcodes=[{'raw':'(01)'+GTIN+'(17)350401(10)LOT'}])


def test_exact_catalogue_mapping_and_printed_crosscheck():
    r=resolve_ref(observation(),CAT)
    assert r['code']=='413.040S' and r['catalog_resolution']=='matched'
    assert assess_label(r)['fields']['code']['method']=='gtin_catalogue_ocr'


@pytest.mark.parametrize('ocr',['413.040','413.0405','413.048S','413.040TS'])
def test_catalogue_never_repairs_discordant_ocr(ocr):
    r=resolve_ref(observation(ocr),CAT)
    assert r['code'] is None and r['catalog_resolution']=='conflict'
    assert r['catalog_ref_candidate']=='413.040S' and r['ref_ocr_observations']==[ocr]
    assert assess_label(r)['fields']['code']['status']=='conflict'


def test_missing_catalogue_unknown_gtin_and_ai_only_gtin_never_supply_ref():
    assert resolve_ref(observation(),None)['code'] is None
    assert resolve_ref(observation(),{})['catalog_resolution']=='unknown_gtin'
    r=observation();r['barcodes']=[];r['gtin']=GTIN
    assert resolve_ref(r,CAT)['code'] is None


def test_catalogue_ref_without_printed_ocr_stays_reviewable():
    r=resolve_ref(observation(None),CAT)
    assert r['code']=='413.040S' and r['catalog_resolution']=='ocr_missing'
    assert assess_label(r)['fields']['code']['status']=='unverified'


def test_csv_preserves_leading_zero_and_rejects_bad_check_digit_and_conflicts(tmp_path):
    f=tmp_path/'catalog.csv';f.write_text(f'gtin,ref,descrizione\n{GTIN},413.040S,Vite\n')
    assert list(read_catalog(f))==[GTIN]
    f.write_text(f'gtin,ref,descrizione\n{GTIN},413.040S,Vite\n{GTIN},413.048S,Vite\n')
    with pytest.raises(ValueError):read_catalog(f)
    f.write_text('gtin,ref,descrizione\n07611819268624,413.040S,Vite\n')
    with pytest.raises(ValueError):read_catalog(f)


def scene(tmp_path,monkeypatch):
    p=tmp_path/'patient.png';im=Image.new('RGB',(1000,1000),'white');d=ImageDraw.Draw(im)
    d.rectangle([0,0,999,299],fill=(255,0,0));d.text((10,10),'PAZIENTE CARTELLA CLINICA SECRET',fill='black')
    d.rectangle([100,500,900,700],fill=(0,0,255));im.save(p)
    regions=[dict(page=1,bbox=[100,500,900,700],rotation=0)]
    a=dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(),regions=regions,approved=True,labels_only_confirmed=True)
    monkeypatch.setattr('local_label_reader.prepare_document',lambda _:a)
    monkeypatch.setattr('label_pipeline.decode_barcodes',lambda _:[])
    monkeypatch.setattr('label_pipeline.local_ref_evidence',lambda _:{'status':'unreadable','candidates':[]})
    return p,a


def test_external_payload_contains_no_header_pixels_or_header_calls(tmp_path,monkeypatch):
    path,approval=scene(tmp_path,monkeypatch);sent=[]
    def create(**kwargs):
        assert kwargs['store'] is False
        assert kwargs['text']['format']['name'] in {'single_label','independent_label_read'}
        for message in kwargs['input']:
            for content in message['content']:
                if content['type']!='input_image':continue
                picture=Image.open(BytesIO(base64.b64decode(content['image_url'].split(',')[1]))).convert('RGB')
                assert picture.width/picture.height==pytest.approx(4)
                assert not any(r>220 and g<30 and b<30 for r,g,b in __import__('numpy').asarray(picture).reshape(-1,3)),'Patient header sent externally'
                sent.append(picture.size)
        return {'code':'413.040S','lot':'LOT','expiry':'2035-04-01'}
    client=SimpleNamespace(responses=SimpleNamespace(create=create))
    result=analyze_labels(path,client,'fake',{'properties':{'code':{},'lot':{},'expiry':{}}},lambda r:r,privacy_approval=approval)
    assert len(sent)==2 and result['clinical_record'] is None and result['clinic_name'] is None


@pytest.mark.parametrize('change',['absent','hash','header','not_confirmed'])
def test_privacy_fails_closed_before_any_model_request(tmp_path,monkeypatch,change):
    path,approval=scene(tmp_path,monkeypatch)
    approval=json.loads(json.dumps(approval))
    if change=='absent':approval=None
    elif change=='hash':approval['sha256']='wrong'
    elif change=='header':approval['regions'][0]['bbox']=[0,0,1000,300]
    else:approval['labels_only_confirmed']=False
    def forbidden(**kwargs):raise AssertionError('No model request authorized')
    with pytest.raises(ValueError,match='Privacy'):
        analyze_labels(path,SimpleNamespace(responses=SimpleNamespace(create=forbidden)),'fake',{'properties':{}},lambda r:r,privacy_approval=approval)


def test_logs_redact_actual_environment_secret_without_echoing_it(monkeypatch):
    secret='sk-TEST-NEVER-A-REAL-KEY-1234567890';monkeypatch.setenv('OPENAI_API_KEY',secret)
    safe,leaked=redact('request failed Authorization: Bearer '+secret)
    assert leaked and secret not in safe and '[REDACTED]' in safe
    safe,leaked=redact('normal evaluation output')
    assert not leaked and safe=='normal evaluation output'


def test_live_runner_does_not_call_model_without_key(monkeypatch):
    import scripts.run_ocr_live as runner
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    monkeypatch.setattr(runner.subprocess,'Popen',lambda *a,**kw:pytest.fail('Unexpected process'))
    assert runner.main([])==4


def test_live_wrapper_blocks_and_cleans_a_secret_emitted_by_child(tmp_path,monkeypatch,capsys):
    import io
    import scripts.run_ocr_live as runner
    secret='sk-FAKE-CHILD-LEAK-123456789012345';monkeypatch.setenv('OPENAI_API_KEY',secret)
    (tmp_path/'summary.json').write_text(json.dumps({'accepted':True,'status':'COMPLETED'}))
    process=SimpleNamespace(stdout=io.StringIO('provider debug '+secret+'\n'),wait=lambda:0)
    monkeypatch.setattr(runner.subprocess,'Popen',lambda *a,**kw:process)
    result=runner.main(['--out',str(tmp_path),'--privacy-manifest','manifest.json','--gtin-catalog','catalog.csv'])
    assert result==2 and secret not in capsys.readouterr().out
    assert secret not in (tmp_path/'live.log').read_text()
    assert json.loads((tmp_path/'summary.json').read_text())['accepted'] is False


def test_jpeg_compression_and_exif_resize_warnings_are_local(tmp_path):
    from image_quality import acquisition_report
    from label_pipeline import render_pages
    p=tmp_path/'compressed.jpg';im=Image.new('RGB',(600,900),'white')
    exif=Image.Exif();exif[40962]=3000;exif[40963]=4000
    im.save(p,quality=10,exif=exif)
    result=acquisition_report(render_pages(p)[0],[])
    assert result['resized_metadata']
    assert any('compressione' in s for s in result['warnings'])
    assert any('ridimensionata' in s for s in result['warnings'])


def test_real_small_symbols_recover_from_measured_finder_rois():
    # Product-only fixture: no patient header is checked into the repository.
    from label_geometry import locate_datamatrix_labels
    from datamatrix_reader import decode_label_region
    source=Image.open(Path('tests/fixtures/synthes_mixed_angles/labels.png'))
    regions=locate_datamatrix_labels(source)
    results=[b for r in regions for b in decode_label_region(source,r) if not b.get('error')]
    lots={b['lot'] for b in results}
    assert {'92021P0','470L625','11598P5','46993P5','470L068'}<=lots
    assert any(b.get('decode_scope')=='local_finder_roi' for b in results)
