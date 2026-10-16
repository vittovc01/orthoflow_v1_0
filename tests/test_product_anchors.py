from pathlib import Path
from PIL import Image,ImageDraw
import pytest
from product_anchors import dominant_turn,turn_box


@pytest.mark.parametrize('angle',[0,90,180,270])
def test_boxes_round_trip_without_losing_edges(angle):
    box=[120,230,570,680]
    assert turn_box(turn_box(box,angle),(-angle)%360)==box


def test_decoded_orientation_is_independent_of_page_shape_and_count():
    assert dominant_turn([{'turn':270}])==270
    assert dominant_turn([{'turn':90}]*6)==90
    assert dominant_turn([{'turn':0},{'turn':90},{'turn':180},{'turn':270}])==0
    assert dominant_turn([], [{'rotation':180}]*3)==180


def synthetic_sheet():
    # Existing product-only fixtures on an unrelated generated table. No case data.
    page=Image.new('RGB',(2600,1800),(185,184,180));draw=ImageDraw.Draw(page)
    draw.rectangle((80,80,2400,400),fill=(255,0,255))
    draw.text((100,120),'PATIENT - Cartella Clinica - Data Impianto',font_size=42,fill='black')
    truth=[]
    root=Path(__file__).parent/'fixtures'/'santa_lucia'
    for i,n in enumerate((1,3,5,6,7,8,9)):
        label=Image.open(root/f'{n:02}.png').convert('RGB');label.thumbnail((660,240))
        x,y=280+(i%3)*750,650+(i//3)*330
        page.paste(label,(x,y))
        truth.append([x/page.width*1000,y/page.height*1000,
                      (x+label.width)/page.width*1000,(y+label.height)/page.height*1000])
    return page,truth


@pytest.mark.parametrize('angle',[0,90,180,270])
def test_logo_fallback_keeps_all_seven_on_unrelated_rotated_forms(angle):
    from region_privacy import safe_product_regions,product_canvas
    page,truth=synthetic_sheet()
    rotated=page.rotate(angle,expand=True)
    # No finder anchors supplied: exercise independent fallback, not the old finder.
    accepted,rejected=safe_product_regions(rotated,[])
    assert len(accepted)==7 and not rejected
    boxes=[turn_box(r['bbox'],(-angle)%360) for r in accepted]
    assert all(b[1]>300 for b in boxes)  # Never crop the synthetic clinical header.
    for expected in truth:
        def coverage(box):
            x=max(0,min(box[2],expected[2])-max(box[0],expected[0]))
            y=max(0,min(box[3],expected[3])-max(box[1],expected[1]))
            return x*y/((expected[2]-expected[0])*(expected[3]-expected[1]))
        assert max(map(coverage,boxes))>.8
    safe=product_canvas(rotated,accepted).rotate((-angle)%360,expand=True)
    assert safe.getpixel((200,200))==(255,255,255)


def test_literal_ocr_tsv_quotes_cannot_swallow_subsequent_ref_rows(monkeypatch):
    from types import SimpleNamespace
    from label_pipeline import local_ref_evidence
    monkeypatch.setattr('shutil.which',lambda _: '/usr/bin/tesseract')
    tsv=b'level\tconf\ttext\n5\t90\t"\n5\t95\t413.016S\n'
    monkeypatch.setattr('subprocess.run',lambda *a,**k:SimpleNamespace(stdout=tsv))
    result=local_ref_evidence(Image.new('RGB',(300,100),'white'))
    assert result['candidates']==['413.016S']
    assert all('\t' not in read for read in result['reads'])
