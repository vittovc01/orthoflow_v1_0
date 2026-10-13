from PIL import Image, ImageDraw
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


def test_two_physical_finders_remain_two_across_orientation_passes():
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
    for turn in (0,90,180,270):
        regions=locate_datamatrix_labels(im.rotate(turn,expand=True))
        assert len(regions)==2
        assert all(r['geometry_source']=='local_datamatrix_finder' for r in regions)
