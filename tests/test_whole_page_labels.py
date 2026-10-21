import base64
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from whole_page_labels import analyze_labels, merge_reads, observations, WholePageReadError, failure_reason, vision_options, prepare_page


def label(box, code='4515-70-005', lot='140664P', expiry='2036-02-29'):
    return dict(bbox=box, rotation=0, code=code, lot=lot, expiry=expiry,
                quantity=1, gtin=None, confidence=.9, warning=None)


def response(rows):
    return dict(labels=[dict(bbox=r['bbox'], rotation=r['rotation'],
                  item={k:v for k,v in r.items() if k not in ('bbox','rotation')}) for r in rows], warning=None)


def test_identical_physical_stickers_are_not_deduplicated():
    rows = [label([10,10,300,200]), label([10,300,300,500])]
    merged = merge_reads(rows, list(reversed(rows)))
    assert len(merged) == 2 and sum(r['quantity'] for r in merged) == 2
    assert all(len(r['ocr_reads']) == 2 for r in merged)


def test_ref_disagreement_is_not_silently_corrected():
    a = label([10,10,300,200], code='413.016S')
    b = label([12,12,302,202], code='413.018S')
    row = merge_reads([a], [b])[0]
    assert row['code'] is None and row['lot'] == a['lot']


def test_second_pass_recovers_missing_label():
    a, b = label([10,10,300,200]), label([600,10,900,200])
    merged = merge_reads([a], [b,a])
    assert len(merged) == 2 and 'seconda lettura' in merged[1]['warning']


def test_both_independent_reads_overlap_and_encode_the_full_page_once(tmp_path, monkeypatch):
    from threading import Barrier
    path = tmp_path/'source.png'
    Image.new('RGB',(20,20)).save(path)
    both_started = Barrier(2, timeout=3)
    calls, encodings = [], []
    from whole_page_labels import image_url as encode
    def encode_once(image):
        encodings.append(1)
        return encode(image)
    monkeypatch.setattr('whole_page_labels.image_url', encode_once)
    monkeypatch.setattr('region_privacy.safe_product_regions', lambda page:([], []))
    def create(**kwargs):
        calls.append(kwargs)
        both_started.wait()  # deadlocks/fails if requests are serialized
        return response([label([10,10,900,900])])
    result = analyze_labels(path, SimpleNamespace(responses=SimpleNamespace(create=create)),
                            'gpt-6-astra', {}, lambda x:x)
    assert len(calls) == 2 and len(encodings) == 1 and len(result['items']) == 1
    assert result['items'][0]['code'] == '4515-70-005'
    assert calls[0]['input'][0]['content'][1] == calls[1]['input'][0]['content'][1]
    assert len(result['items'][0]['ocr_reads']) == 2
    assert len({c['input'][0]['content'][0]['text'] for c in calls}) == 2


def test_ambiguous_positions_do_not_establish_consensus():
    rows = [label([10,10,300,200]), label([10,10,310,210])]
    merged = merge_reads(rows, rows)
    assert all(r['code'] is None for r in merged)


def test_different_partial_outlines_do_not_double_count_a_physical_label():
    first = [label([0,400,400,600]),label([600,100,800,800])]
    second = [label([100,450,300,550]),label([650,250,750,650])]
    assert len(merge_reads(first,second)) == 2
    assert all(r['code'] == '4515-70-005' for r in merge_reads(first,second))


def test_agreed_product_multiset_preserves_physical_multiplicity_despite_bad_boxes():
    first = [label([10,10,200,200]),label([10,700,200,900]),
             label([500,10,700,200],lot='OTHER')]
    second = [label([700,700,900,900]),label([700,400,900,600]),
              label([10,400,200,600],lot='OTHER')]
    merged = merge_reads(first, second)
    assert len(merged) == 3
    assert sum(r['quantity'] for r in merged if r['lot'] == '140664P') == 2
    assert all(len(r['ocr_reads']) == 2 for r in merged)


def test_normalized_rows_without_local_crop_evidence_remain_reviewable():
    from ai_ocr import normalize_ai_items
    from ocr_review import build_review
    row = label([10,10,300,200])
    row['label_id'] = 'whole-page-row'
    normalized = normalize_ai_items({'items':[row]})
    assert normalized[0]['local_ref_evidence'] is None
    assert len(build_review({'items':normalized})['items']) == 1


@pytest.mark.parametrize('box', [[-1,0,100,100],[0,0,0,100],[0,0,100,1001],[0,0,float('nan'),100]])
def test_invalid_geometry_fails_explicitly(box):
    with pytest.raises(ValueError):
        observations(response([label(box)]))


def test_full_page_reaches_both_reads_even_when_local_detector_fails(tmp_path, monkeypatch):
    source = Image.new('RGB',(160,90),'blue')
    path = tmp_path/'source.png'
    source.save(path)
    boxes = [[20,400,400,580],[20,600,400,780],[450,400,800,580],
             [450,600,800,780],[820,350,950,780],[20,800,400,990],
             [450,800,800,990],[450,200,800,380]]
    rows = [label(box, lot=str(i)) for i,box in enumerate(boxes)]
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        assert kwargs['store'] is False
        url = kwargs['input'][0]['content'][1]['image_url']
        with Image.open(BytesIO(base64.b64decode(url.split(',')[1]))) as image:
            assert image.size == source.size and image.getpixel((0,0)) == (0,0,255)
        return response(rows)
    def fail(*args, **kwargs):
        raise RuntimeError('detector unavailable')
    monkeypatch.setattr('region_privacy.safe_product_regions', fail)
    result = analyze_labels(path, SimpleNamespace(responses=SimpleNamespace(create=create)),
                            'model', {'type':'object'}, lambda x:x)
    assert len(calls) == 2 and len(result['items']) == 8
    assert all(r['crop_data_url'] is None for r in result['items'])
    assert result['annotated_pages'] == [] and result['clinical_record'] is None
    assert all(r['expiry'] == '2036-02-29' for r in result['items'])


def test_both_requests_failing_cannot_return_successful_empty_extraction(tmp_path):
    path = tmp_path/'source.png'
    Image.new('RGB',(20,20)).save(path)
    def fail(**kwargs):
        raise TimeoutError()
    with pytest.raises(RuntimeError, match='entrambe'):
        analyze_labels(path, SimpleNamespace(responses=SimpleNamespace(create=fail)),
                       'model', {}, lambda x:x)


def test_failed_second_request_preserves_first_observations(tmp_path, monkeypatch):
    path = tmp_path/'source.png'
    Image.new('RGB',(20,20)).save(path)
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            raise TimeoutError()
        return response([label([10,10,900,900])])
    monkeypatch.setattr('region_privacy.safe_product_regions', lambda *a:([],[]))
    result = analyze_labels(path, SimpleNamespace(responses=SimpleNamespace(create=create)),
                           'model', {}, lambda x:x)
    assert len(result['items']) == 1 and result['items'][0]['warning']


def test_production_entry_point_uses_whole_page_reader():
    import inspect
    import ai_ocr
    assert 'from whole_page_labels import analyze_labels' in inspect.getsource(ai_ocr.analyze_document)


def test_full_page_model_defaults_do_not_change_ddt_model(monkeypatch):
    import ai_ocr
    monkeypatch.setattr(ai_ocr,'_secret',lambda name,default='': default)
    status = ai_ocr.ai_status()
    assert status['label_model'] == 'gpt-5.4-mini'
    assert status['model'] == 'gpt-5-mini'
    assert vision_options(status['label_model']) == ('original',{'reasoning':{'effort':'low'}})
    assert vision_options('gpt-4.1') == ('high',{})


def test_original_detail_bounds_whole_image_without_cropping():
    page = Image.new('RGB',(160,90),'blue')
    assert prepare_page(page) is page
    bounded = prepare_page(page,patch_budget=4)
    import math
    assert math.ceil(bounded.width/32)*math.ceil(bounded.height/32) <= 4
    assert bounded.getpixel((0,0)) == (0,0,255)
    assert bounded.getpixel((bounded.width-1,bounded.height-1)) == (0,0,255)
    assert page.size == (160,90)


def test_mini_not_available_never_upgrades_to_an_expensive_model(tmp_path,monkeypatch):
    path = tmp_path/'source.png'
    Image.new('RGB',(20,20)).save(path)
    calls = []
    class ModelUnavailable(Exception):
        status_code = 404
    def create(**kwargs):
        calls.append(kwargs)
        assert kwargs['model'] == 'gpt-5.4-mini'
        assert kwargs['input'][0]['content'][1]['detail'] == 'original'
        assert kwargs['reasoning'] == {'effort':'low'}
        raise ModelUnavailable()
    monkeypatch.setattr('region_privacy.safe_product_regions',lambda *a:([],[]))
    with pytest.raises(WholePageReadError):
        analyze_labels(path,SimpleNamespace(responses=SimpleNamespace(create=create)),
                       'gpt-5.4-mini',{},lambda x:x)
    assert len(calls) == 2


def test_existing_session_upgrades_cached_analyzer(monkeypatch):
    import ai_ocr
    import whole_page_runtime
    stale = lambda *a, **k: 'old-crop-only-reader'
    monkeypatch.setattr(ai_ocr, 'analyze_document', stale)
    whole_page_runtime._signatures.clear()
    whole_page_runtime.refresh_ocr_modules()
    assert ai_ocr.analyze_document is not stale


def test_provider_diagnostics_do_not_echo_secrets():
    error = RuntimeError('secret credential or clinical payload')
    assert failure_reason(error) == 'RuntimeError'


def test_quota_has_only_two_inflight_reads_and_no_retries_or_fallback(tmp_path):
    from whole_page_labels import WholePageReadError
    from tests.test_ai_failures import ProviderError
    path = tmp_path/'source.png'
    Image.new('RGB',(20,20)).save(path)
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        raise ProviderError('insufficient_quota')
    with pytest.raises(WholePageReadError) as error:
        analyze_labels(path, SimpleNamespace(responses=SimpleNamespace(create=create)),
                       'gpt-6-astra', {}, lambda x:x)
    assert len(calls) == 2 and error.value.kind == 'quota'
    assert 'non serve rifare la foto' in error.value.public_reason
    assert 'secret' not in error.value.public_reason


def test_quota_in_second_read_preserves_first_labels(tmp_path, monkeypatch):
    from tests.test_ai_failures import ProviderError
    path = tmp_path/'source.png'
    Image.new('RGB',(20,20)).save(path)
    calls = []
    def create(**kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise ProviderError('insufficient_quota')
        return response([label([10,10,900,900])])
    monkeypatch.setattr('region_privacy.safe_product_regions', lambda *a:([],[]))
    result = analyze_labels(path, SimpleNamespace(responses=SimpleNamespace(create=create)),
                            'gpt-6-astra', {}, lambda x:x)
    assert len(calls) == 2 and len(result['items']) == 1
    assert any('Quota' in warning for warning in result['detection_warnings'])


def test_full_page_reader_keeps_sterile_ref_suffix_guard(tmp_path, monkeypatch):
    path = tmp_path/'source.png'
    Image.new('RGB',(20,20)).save(path)
    row = label([10,10,900,900], code='413.016')
    row['is_sterile'] = True
    monkeypatch.setattr('region_privacy.safe_product_regions', lambda *a:([],[]))
    client = SimpleNamespace(responses=SimpleNamespace(create=lambda **k: response([row])))
    result = analyze_labels(path, client, 'model', {}, lambda x:x)
    assert result['items'][0]['code'] is None
    assert result['items'][0]['ref_original'] == '413.016'
    assert 'suffisso' in result['items'][0]['warning']


def test_failed_full_page_analysis_exposes_safe_reason(tmp_path):
    from ocr_service import analyze_documents
    from ocr_repository import OriginalDocument
    image = BytesIO()
    Image.new('RGB',(20,20)).save(image,format='PNG')
    def fail(*args, **kwargs):
        from whole_page_labels import WholePageReadError
        raise WholePageReadError(1, ['BadRequestError HTTP 400'])
    result = analyze_documents([OriginalDocument('products.png',image.getvalue())], analyzer=fail)
    assert result['documents'][0]['status'] == 'failed'
    assert 'BadRequestError HTTP 400' in result['detection_warnings'][0]
    assert not result['items']


def test_provider_limit_does_not_resubmit_remaining_documents():
    from ocr_service import analyze_documents
    from ocr_repository import OriginalDocument
    image = BytesIO()
    Image.new('RGB',(20,20)).save(image,format='PNG')
    calls = []
    def fail(*args, **kwargs):
        from whole_page_labels import WholePageReadError
        calls.append(1)
        raise WholePageReadError(1, ['Quota API esaurita; non serve rifare la foto'], kind='quota')
    result = analyze_documents([OriginalDocument('a.png',image.getvalue()),
                                OriginalDocument('b.png',image.getvalue())], analyzer=fail)
    assert calls == [1]
    assert all(d['status'] == 'failed' and d['failure_kind'] == 'quota' for d in result['documents'])
    assert all('nuova foto' not in w for w in result['detection_warnings'])


def test_first_read_failure_keeps_successful_second_read(tmp_path, monkeypatch):
    from tests.test_ai_failures import ProviderError
    path = tmp_path/'source.png'
    Image.new('RGB', (20,20)).save(path)
    monkeypatch.setattr('region_privacy.safe_product_regions', lambda page:([], []))
    def create(**kwargs):
        if 'Seconda lettura' not in kwargs['input'][0]['content'][0]['text']:
            raise ProviderError('insufficient_quota')
        return response([label([10,10,900,900])])
    result = analyze_labels(path, SimpleNamespace(responses=SimpleNamespace(create=create)),
                            'gpt-6-astra', {}, lambda x:x)
    assert len(result['items']) == 1
    assert result['items'][0]['warning']
    assert any('Quota' in w for w in result['detection_warnings'])
