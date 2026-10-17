import base64
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from whole_page_labels import analyze_labels, merge_reads, observations, WholePageReadError, failure_reason


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


def test_ambiguous_positions_do_not_establish_consensus():
    rows = [label([10,10,300,200]), label([10,10,310,210])]
    merged = merge_reads(rows, rows)
    assert all(r['code'] is None for r in merged)


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
        assert len(calls) == 2  # local geometry runs only after transcription
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
