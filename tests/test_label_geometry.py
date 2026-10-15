from PIL import Image, ImageDraw
from types import SimpleNamespace
import pytest
from label_geometry import finder_orientation, locate_datamatrix_labels


@pytest.mark.parametrize('edges,expected',[
    ((.3,.8,.8,.3),(-1,0,0)),
    ((.3,.8,.3,.8),(0,1,270)),
    ((.8,.3,.3,.8),(1,0,180)),
    ((.8,.3,.8,.3),(0,-1,90)),
    ((.5,.5,.5,.4),None),
])
def test_solid_finder_edges_control_orientation(edges,expected):
    assert finder_orientation(*edges)==expected


def test_blank_page_has_no_physical_anchors():
    assert locate_datamatrix_labels(Image.new('RGB',(600,800),'white'))==[]


def test_clinic_cross_is_not_a_datamatrix_finder():
    im=Image.new('RGB',(600,800),'white');draw=ImageDraw.Draw(im)
    draw.rectangle((280,200,290,230),fill='black')
    draw.rectangle((270,210,300,220),fill='black')
    assert locate_datamatrix_labels(im)==[]


def finder_page():
    im=Image.new('RGB',(1000,600),(202,200,195));draw=ImageDraw.Draw(im)
    for start in (80,550):
        draw.rectangle((start,100,start+300,200),fill=(205,208,198))
        for row in range(14):
            for col in range(14):
                dark=(col==0 or row==13 or (row==0 and col%2==0)
                      or (col==13 and row%2==0)
                      or (0<row<13 and 0<col<13 and (row+col*3)%4<2))
                if dark:
                    draw.rectangle((start+260+col*2,150+row*2,
                                    start+261+col*2,151+row*2),fill='black')
    return im


def test_two_physical_finders_remain_two_across_orientation_passes():
    im = finder_page()
    for turn in (0,90,180,270):
        regions=locate_datamatrix_labels(im.rotate(turn,expand=True))
        assert len(regions)==2
        assert all(r['geometry_source']=='local_datamatrix_finder' for r in regions)


def test_large_scanned_symbols_calibrate_morphology_without_reading_ref(monkeypatch):
    import zxingcpp
    point = lambda x,y: SimpleNamespace(x=x,y=y)
    position = SimpleNamespace(top_left=point(0,0), top_right=point(56,0),
                               bottom_right=point(56,56), bottom_left=point(0,56))
    barcode = SimpleNamespace(format=zxingcpp.BarcodeFormat.DataMatrix, position=position)
    monkeypatch.setattr(zxingcpp, 'read_barcodes', lambda image: [barcode])
    im = finder_page().resize((2000,1200), Image.Resampling.NEAREST)
    for turn in (0,90,180,270):
        assert len(locate_datamatrix_labels(im.rotate(turn,expand=True))) == 2


@pytest.mark.parametrize('turn',[0,90,180,270])
def test_measured_stickers_preserve_seven_pieces_and_inclined_ref_headers(turn):
    from pathlib import Path
    from label_pipeline import crop_region
    path=Path(__file__).parent/'fixtures'/'synthes_mixed_angles'/'labels.png'
    source=Image.open(path)
    image=source.rotate(turn,expand=True)
    regions=locate_datamatrix_labels(image)
    assert len(regions)==7
    assert all(r['geometry_source']=='local_datamatrix_sticker' for r in regions)
    assert all(r['rotation']==(-turn)%360 for r in regions)
    assert all(abs(r['deskew_angle'])<20 for r in regions)
    # Independent printed REF header boxes in the fixture, not detector output.
    headers=[(26,14,110,35),(303,17,380,43),(592,30,670,53),
             (30,118,120,140),(304,116,385,140),(609,158,690,194),
             (25,226,110,249)]
    for left,top,right,bottom in headers:
        points=[(left,top),(right,top),(right,bottom),(left,bottom)]
        for _ in range(turn//90):
            points=[(y,source.width-x) for x,y in points]
            # Quarter-turn transforms need the dimensions of each current image.
            source=source.rotate(90,expand=True)
        # Reset dimensions for the next independent annotation.
        source=Image.open(path)
        lo=(min(p[0] for p in points),min(p[1] for p in points))
        hi=(max(p[0] for p in points),max(p[1] for p in points))
        containing=[r for r in regions if r['bbox'][0]*image.width/1000 <= lo[0]
                    and r['bbox'][1]*image.height/1000 <= lo[1]
                    and r['bbox'][2]*image.width/1000 >= hi[0]
                    and r['bbox'][3]*image.height/1000 >= hi[1]]
        assert len(containing)==1, (turn,lo,hi,regions)
