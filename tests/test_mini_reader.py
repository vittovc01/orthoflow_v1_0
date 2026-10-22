"""Mini migration, native-pixel preservation and consumption: no paid API calls."""
from types import SimpleNamespace
from io import BytesIO
from threading import Barrier
import math

import pytest
from PIL import Image
from ocr_costs import response_usage, usage_totals
from whole_page_labels import analyze_labels, prepare_page, WholePageReadError
from tests.test_whole_page_labels import response, label


def test_legacy_secret_cannot_reactivate_astra(monkeypatch):
    import ai_ocr
    monkeypatch.setattr(ai_ocr,'_secret',lambda name,default='': 'gpt-6-astra' if name=='SCARICO_FULL_PAGE_MODEL' else default)
    assert ai_ocr.ai_status()['label_model']=='gpt-6.1-sol'
    assert ai_ocr.ai_status()['model']=='gpt-5-mini'


def test_native_camscanner_resolution_is_not_reduced_for_mini():
    page=Image.new('RGB',(2448,3316),'white')
    try:
        assert prepare_page(page,patch_budget=10000,max_dimension=6000) is page
    finally:page.close()


@pytest.mark.parametrize('size',[(4500,6000),(12000,100)])
def test_oversized_page_keeps_all_corners_within_mini_limits(size):
    page=Image.new('RGB',size,'blue')
    prepared=prepare_page(page,patch_budget=10000,max_dimension=6000)
    try:
        assert max(prepared.size)<=6000
        assert math.ceil(prepared.width/32)*math.ceil(prepared.height/32)<=10000
        assert prepared.getpixel((0,0))==(0,0,255)
        assert prepared.getpixel((prepared.width-1,prepared.height-1))==(0,0,255)
    finally:
        if prepared is not page:prepared.close()
        page.close()


def usage():
    return dict(input_tokens=10000,output_tokens=2000,
                input_tokens_details={'cached_tokens':1000},output_tokens_details={'reasoning_tokens':500})


def test_cost_includes_reasoning_once_and_discounts_cached_input():
    result=response_usage({'usage':usage()},'gpt-5.4-mini')
    assert result['estimated_cost_usd']==pytest.approx(.015825)
    assert result['total_tokens']==12000 and result['reasoning_tokens']==500
    assert usage_totals([result,result])['estimated_cost_usd']==pytest.approx(.03165)
    assert response_usage({},'gpt-5.4-mini') is None
    assert response_usage({'usage':usage()},'unknown')['estimated_cost_usd'] is None
    broken=usage();broken['input_tokens_details']={'cached_tokens':'bad'}
    assert response_usage({'usage':broken},'gpt-5.4-mini')['cached_input_tokens']==0


def test_two_mini_reads_keep_consensus_and_return_only_usage_metadata(tmp_path,monkeypatch):
    path=tmp_path/'scan.png';Image.new('RGB',(40,40),'white').save(path)
    barrier=Barrier(2,timeout=3)
    calls=[]
    rows=[label([10,10,400,300]),label([10,400,400,700])]
    def create(**kwargs):
        calls.append(kwargs)
        assert kwargs['model']=='gpt-5.4-mini' and kwargs['store'] is False
        assert kwargs['input'][0]['content'][1]['detail']=='original'
        barrier.wait()
        return dict(response(rows),usage=usage())
    monkeypatch.setattr('whole_page_labels.optional_product_regions',lambda page:([],False))
    result=analyze_labels(path,SimpleNamespace(responses=SimpleNamespace(create=create)),
                          'gpt-5.4-mini',{},lambda x:x)
    assert len(calls)==2 and len(result['items'])==2
    assert all(len(r['ocr_reads'])==2 for r in result['items'])
    assert len(result['api_usage'])==2 and {r['read'] for r in result['api_usage']}=={1,2}
    assert usage_totals(result['api_usage'])['estimated_cost_usd']==pytest.approx(.03165)
    assert all('image_url' not in r and 'source_text' not in r for r in result['api_usage'])


def test_consumption_survives_two_billed_but_unparseable_responses(tmp_path,monkeypatch):
    path=tmp_path/'scan.png';Image.new('RGB',(40,40),'white').save(path)
    monkeypatch.setattr('whole_page_labels.optional_product_regions',lambda page:([],False))
    client=SimpleNamespace(responses=SimpleNamespace(create=lambda **k:{'usage':usage()}))
    def invalid(_):raise ValueError('invalid json')
    with pytest.raises(WholePageReadError) as error:
        analyze_labels(path,client,'gpt-5.4-mini',{},invalid)
    assert len(error.value.api_usage)==2


def test_real_entrypoint_forces_mini_and_persists_usage_in_app_thread(tmp_path,monkeypatch):
    import ai_ocr
    from threading import current_thread
    path=tmp_path/'scan.png';Image.new('RGB',(40,40),'white').save(path)
    monkeypatch.setattr(ai_ocr,'_secret',lambda name,default='':
        {'OPENAI_API_KEY':'test-key','ENABLE_AI_OCR':'true','SCARICO_FULL_PAGE_MODEL':'gpt-6-astra'}.get(name,default))
    calls=[]
    def create(**kwargs):
        calls.append(kwargs['model'])
        assert kwargs['service_tier']=='default'
        assert kwargs['input'][0]['content'][1]['detail']=='original'
        import json
        return SimpleNamespace(usage=usage(),output_text=json.dumps(response([label([10,10,900,900])])))
    monkeypatch.setattr(ai_ocr,'OpenAI',lambda **k:SimpleNamespace(responses=SimpleNamespace(create=create)))
    monkeypatch.setattr('whole_page_labels.optional_product_regions',lambda page:([],False))
    recorded=[]
    monkeypatch.setattr(ai_ocr,'_track_label_usage',lambda reads,suffix,outcome:recorded.append((reads,suffix,outcome,current_thread().name)))
    result=ai_ocr.analyze_document(str(path),'scarico_sala')
    assert calls==['gpt-6.1-sol']*2 and len(result['items'])==1
    assert len(recorded)==1 and len(recorded[0][0])==2 and recorded[0][2]=='OK'
    assert recorded[0][3]==current_thread().name


def test_usage_batch_records_both_reads_without_product_data(monkeypatch):
    import ai_ocr,streamlit as st,supabase
    recorded=[]
    class Client:
        def table(self,name):assert name=='ocr_usage';return self
        def insert(self,rows):recorded.extend(rows);return self
        def execute(self):return SimpleNamespace(data=[])
    monkeypatch.setattr(ai_ocr,'_secret',lambda name,default='':{'SUPABASE_URL':'https://example.invalid','SUPABASE_SERVICE_KEY':'test-key'}.get(name,default))
    monkeypatch.setattr(st,'session_state',{'user':'test-user'})
    monkeypatch.setattr(supabase,'create_client',lambda *a:Client())
    read=response_usage({'usage':usage()},'gpt-5.4-mini')
    ai_ocr._track_label_usage([read,read],'.pdf','OK')
    assert len(recorded)==2 and all(r['modello']=='gpt-5.4-mini' for r in recorded)
    assert sum(r['costo_usd'] for r in recorded)==pytest.approx(.03165)
    assert set(recorded[0])=={'utente','modulo','modello','input_tokens','output_tokens','total_tokens','costo_usd','file_tipo','esito'}
    monkeypatch.setattr(supabase,'create_client',lambda *a: (_ for _ in ()).throw(TimeoutError()))
    ai_ocr._track_label_usage([read],'.pdf','OK')  # telemetry outages do not discard OCR


def test_duplicate_document_does_not_duplicate_usage():
    from ocr_repository import OriginalDocument
    from ocr_service import analyze_documents
    image=BytesIO();Image.new('RGB',(40,40)).save(image,format='PNG')
    read=response_usage({'usage':usage()},'gpt-5.4-mini')
    calls=[]
    def analyzer(*a,**k):
        calls.append(1)
        return {'items':[],'api_usage':[read,read],'ocr_model':'gpt-5.4-mini'}
    result=analyze_documents([OriginalDocument('one.png',image.getvalue()),OriginalDocument('two.png',image.getvalue())],analyzer=analyzer)
    assert calls==[1] and len(result['api_usage'])==2
    assert [d['status'] for d in result['documents']]==['analyzed','duplicate']


@pytest.mark.parametrize('model',['gpt-5.4-mini'])
def test_mini_second_read_is_rotated_full_page_and_restores_coordinates(tmp_path,monkeypatch,model):
    import base64
    path=tmp_path/'vertical.png'
    original=Image.new('RGB',(80,160),'white');original.putpixel((0,0),(255,0,0));original.save(path)
    monkeypatch.setattr('whole_page_labels.optional_product_regions',lambda page:([],False))
    monkeypatch.setattr('whole_page_labels.page_barcode_evidence',lambda page:[])
    sizes=[]
    def create(**kwargs):
        content=kwargs['input'][0]['content']
        page=Image.open(BytesIO(base64.b64decode(content[1]['image_url'].split(',')[1])))
        sizes.append(page.size)
        second='Seconda lettura' in content[0]['text']
        assert page.size==((160,80) if second else (80,160))
        assert page.getpixel((159,0) if second else (0,0))==(255,0,0)
        box=[600,100,900,300] if second else [100,100,300,400]
        return response([label(box)])
    result=analyze_labels(path,SimpleNamespace(responses=SimpleNamespace(create=create)),
                          model,{},lambda x:x)
    assert sorted(sizes)==[(80,160),(160,80)] and len(result['items'])==1
    assert result['items'][0]['ocr_reads'][0]['bbox']==result['items'][0]['ocr_reads'][1]['bbox']


def test_sol_standard_cost_counts_both_reads():
    result=response_usage({'usage':usage()},'gpt-6.1-sol')
    assert result['estimated_cost_usd']==pytest.approx(.0381)
    assert usage_totals([result,result])['estimated_cost_usd']==pytest.approx(.0762)


def test_sol_uses_astra_native_full_page_view_for_both_reads(tmp_path,monkeypatch):
    import base64
    path=tmp_path/'native.png'
    page=Image.new('RGB',(80,160),'white');page.putpixel((0,0),(255,0,0));page.save(path)
    monkeypatch.setattr('whole_page_labels.optional_product_regions',lambda page:([],False))
    monkeypatch.setattr('whole_page_labels.page_barcode_evidence',lambda page:[])
    calls=[]
    def create(**kwargs):
        content=kwargs['input'][0]['content']
        image=Image.open(BytesIO(base64.b64decode(content[1]['image_url'].split(',')[1])))
        assert image.size==(80,160) and image.getpixel((0,0))==(255,0,0)
        assert kwargs['model']=='gpt-6.1-sol' and kwargs['service_tier']=='default'
        calls.append(content[0]['text'])
        return response([label([100,100,300,400])])
    result=analyze_labels(path,SimpleNamespace(responses=SimpleNamespace(create=create)),
                          'gpt-6.1-sol',{},lambda x:x)
    assert len(calls)==2 and sum('Seconda lettura' in p for p in calls)==1
    assert len(result['items'])==1 and result['items'][0]['code']
