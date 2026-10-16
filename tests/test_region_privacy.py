import base64
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from PIL import Image,ImageDraw
from region_privacy import safe_product_regions,product_canvas

FIXTURE=Path(__file__).parent/'fixtures'/'federico_labels.png'


def test_federico_preserves_seven_real_labels_without_header_candidates():
    page=Image.open(FIXTURE)
    accepted,rejected=safe_product_regions(page)
    assert len(accepted)==7
    assert all(r['bbox'][1]>430 for r in accepted+rejected)
    assert all(r['bbox'][3]<605 for r in accepted)


def test_header_never_cropped_returned_or_sent_even_if_ai_proposes_it(tmp_path,monkeypatch):
    import label_pipeline
    page=Image.open(FIXTURE).convert('RGB')
    pen=ImageDraw.Draw(page)
    pen.rectangle((100,300,800,700),fill=(255,0,255))
    # Synthetic canary only: no real patient data is committed in this fixture.
    pen.text((120,320),'PATIENT PRIVATE HEADER - Cartella Clinica - Data Impianto',fill='black',font_size=24)
    path=tmp_path/'private.png';page.save(path)
    captures=[];crop_boxes=[]
    crop=label_pipeline.crop_region
    def guarded_crop(image,box):
        assert box[1]>430, box
        crop_boxes.append(box)
        return crop(image,box)
    monkeypatch.setattr(label_pipeline,'crop_region',guarded_crop)
    def create(**kwargs):
        name=kwargs['text']['format']['name']
        assert name!='procedure_header'
        for message in kwargs['input']:
            for content in message['content']:
                if content.get('type')!='input_image':continue
                im=Image.open(BytesIO(base64.b64decode(content['image_url'].split(',',1)[1]))).convert('RGB')
                captures.append(im)
                # Magenta canary must never cross the boundary, in any image size.
                assert not any(r>200 and b>200 and g<80 for r,g,b in im.getdata())
        if name in ('physical_labels','audited_physical_labels'):
            return {'labels':[{'bbox':[70,160,650,430],'rotation':0}],'layout':'unknown','warning':None}
        return {'code':None,'lot':None,'expiry':None,'quantity':1,'warning':None}
    result=label_pipeline.analyze_labels(path,SimpleNamespace(responses=SimpleNamespace(create=create)),
        'test',{'properties':{'code':{},'lot':{},'expiry':{}}},lambda x:x)
    assert result['physical_label_count']==7
    assert captures and crop_boxes
    assert result['clinical_record'] is None and result['procedure_date'] is None
    for r in result['items']+result['unconfirmed_regions']:
        assert r['bbox'][1]>430
    for entry in result['annotated_pages']:
        im=Image.open(BytesIO(base64.b64decode(entry['page_data_url'].split(',',1)[1]))).convert('RGB')
        assert im.getpixel((im.width//3,im.height//4))==(255,255,255)


def test_blank_form_field_cannot_become_an_external_candidate():
    page=Image.new('RGB',(800,1000),(150,150,150))
    draw=ImageDraw.Draw(page)
    draw.rectangle((100,100,700,250),fill='white')
    draw.text((120,130),'Paziente - Cartella Clinica - Data Impianto',fill='black',font_size=20)
    a,b=safe_product_regions(page,[{'bbox':[100,100,900,300],'rotation':0}])
    assert not a and not b
    assert product_canvas(page,a).getextrema()==((255,255),(255,255),(255,255))


def test_existing_label_families_do_not_lose_true_stickers():
    from label_geometry import locate_datamatrix_labels
    from linear_label_geometry import locate_linear_labels
    root=Path(__file__).parent/'fixtures'
    for name,count in [('depuy_linear/velys.jpg',6),('depuy_linear/attune.jpg',5),
                       ('depuy_linear/atripalda.jpg',4),('synthes_mixed_angles/labels.png',7)]:
        page=Image.open(root/name)
        anchors=locate_datamatrix_labels(page)+locate_linear_labels(page)
        accepted,_=safe_product_regions(page,anchors)
        assert len(accepted)==count, (name,accepted)


def test_missing_local_privacy_dependency_fails_before_any_service_call(tmp_path,monkeypatch):
    import pytest
    import label_pipeline
    path=tmp_path/'input.png';Image.new('RGB',(200,200),'white').save(path)
    monkeypatch.setattr('shutil.which',lambda _:None)
    def forbidden(**kwargs):raise AssertionError('External call before privacy validation')
    with pytest.raises(RuntimeError,match='nessun invio esterno'):
        label_pipeline.analyze_labels(path,SimpleNamespace(responses=SimpleNamespace(create=forbidden)),
            'test',{'properties':{}},lambda x:x)


def test_single_label_photographs_keep_the_complete_ref_end():
    from label_geometry import locate_datamatrix_labels
    for n in (1,2,4):
        page=Image.open(Path(__file__).parent/'fixtures'/'santa_lucia'/f'{n:02}.png')
        accepted,rejected=safe_product_regions(page,locate_datamatrix_labels(page))
        assert len(accepted)==1 and not rejected
        assert accepted[0]['bbox']==[0,0,1000,1000]


def test_original_inputs_use_temporary_paths_and_anonymous_names():
    import ast
    from uuid import uuid4
    source=Path(__file__).resolve().parents[1]/'pages'/'_05_Scarico_Sala_AI_impl.py'
    tree=ast.parse(source.read_text())
    selected=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {'temporary_input_dir','save_local','save_camera'}]
    state={}
    namespace={'Path':Path,'uuid4':uuid4,'st':SimpleNamespace(session_state=state)}
    exec(compile(ast.Module(body=selected,type_ignores=[]),str(source),'exec'),namespace)
    upload=BytesIO(b'%PDF-test-original');upload.name='private-clinical-record.pdf'
    path=Path(namespace['save_local'](upload))
    try:
        assert path.read_bytes()==b'%PDF-test-original'
        assert 'uploads' not in path.parts and 'clinical' not in path.name
    finally:
        state['scarico_input_tempdir'].cleanup()
    assert not path.exists()
