"""Local orientation and independent printed-logo anchors, without clinical data."""
import math
import re
import statistics


def decoded_symbols(page):
    import zxingcpp
    from label_pipeline import gs1_parse
    output=[]
    for barcode in zxingcpp.read_barcodes(page):
        if barcode.format != zxingcpp.BarcodeFormat.DataMatrix:
            continue
        raw=barcode.bytes.decode('utf-8',errors='replace')
        if gs1_parse(raw).get('error'):
            continue
        points=[barcode.position.top_left,barcode.position.top_right,
                barcode.position.bottom_right,barcode.position.bottom_left]
        size=statistics.median(math.hypot(a.x-b.x,a.y-b.y) for a,b in zip(points,points[1:]+points[:1]))
        output.append({'turn':round(barcode.orientation/90)*90%360,'size':size,'angle':barcode.orientation,
                       'center':[(sum(p.x for p in points)/4)/page.width*1000,(sum(p.y for p in points)/4)/page.height*1000]})
    return output


def dominant_turn(symbols, anchors=()):
    turns=[s['turn'] for s in symbols]
    if not turns:
        turns=[r.get('rotation',0)%360 for r in anchors]
    if not turns:return 0
    winner=max(set(turns),key=turns.count)
    # Mixed orientations are legitimate; do not rotate on a weak majority.
    required=1 if symbols else 2
    return winner if turns.count(winner)>=max(required,len(turns)*.75) else 0


def turn_box(box, angle):
    x,y,xx,yy=box
    if angle==90:return [y,1000-xx,yy,1000-x]
    if angle==180:return [1000-xx,1000-yy,1000-x,1000-y]
    if angle==270:return [1000-yy,x,1000-y,xx]
    return list(box)


def turn_region(region, angle):
    result=dict(region)
    for key in ('bbox','finder_bbox'):
        if region.get(key):result[key]=turn_box(region[key],angle)
    result['rotation']=(region.get('rotation',0)-angle)%360
    return result


def logo_regions(page, words, symbols):
    """Recover stickers missed by finder morphology using independent logos.

    Calibrate physical dimensions from decoded symbols on THIS image. No clinic,
    document offset, REF, lot, catalogue entry or expected label count is used.
    Existing geometry remains preferred; this supplies unmatched product anchors.
    """
    if not symbols or not any(re.fullmatch(r'(?:\d{2}\.\d{3}\.\d{3}|\d{3}\.\d{3})(?:S|TS)',w['text']) for w in words):
        return []
    size=statistics.median(s['size'] for s in symbols)
    full=[w for w in words if re.search(r'depuy.?synthes',w['text'],re.I)]
    logo_width=statistics.median(w['w']*page.width/1000 for w in full) if full else size*2
    output=[]
    from label_pipeline import overlap
    # Shorter, separate OCR observations avoid a merged logo spanning two rows.
    for word in sorted(words,key=lambda w:w['w']):
        if not re.search(r'depuy',word['text'],re.I):continue
        x=word['x']*page.width/1000;y=word['y']*page.height/1000
        width=word['w']*page.width/1000;height=word['h']*page.height/1000
        right=x+(width if re.search('synthes',word['text'],re.I) else max(width,logo_width))+size*.25
        bottom=y+height+size*.12
        nearest=min(symbols,key=lambda s:math.hypot(s['center'][0]*page.width/1000-(x+width/2),s['center'][1]*page.height/1000-y))
        distance=math.hypot(nearest['center'][0]*page.width/1000-(x+width/2),nearest['center'][1]*page.height/1000-y)
        angle=nearest['angle'] if distance<size*3 else 0
        angle=(angle+180)%360-180
        if abs(angle)>15:angle=0
        radians=math.radians(angle);u=(math.cos(radians),math.sin(radians));v=(-u[1],u[0])
        corners=[(right+u[0]*dx+v[0]*dy,bottom+u[1]*dx+v[1]*dy)
                 for dx,dy in ((-size*9.7,-size*3.3),(0,-size*3.3),(0,0),(-size*9.7,0))]
        box=[max(0,round(min(p[0] for p in corners)/page.width*1000)),
             max(0,round(min(p[1] for p in corners)/page.height*1000)),
             min(1000,round(max(p[0] for p in corners)/page.width*1000)),
             min(1000,round(max(p[1] for p in corners)/page.height*1000))]
        if any(overlap(box,r['bbox'])>.65 for r in output):continue
        output.append({'bbox':box,'rotation':0,'geometry_source':'local_product_logo'})
    return output


def align_product_crop(crop):
    """Read a symbol's physical orientation to remove small residual label tilt."""
    import zxingcpp
    angles=[]
    from label_pipeline import gs1_parse
    for barcode in zxingcpp.read_barcodes(crop):
        if barcode.format==zxingcpp.BarcodeFormat.DataMatrix and not gs1_parse(barcode.bytes.decode('utf-8',errors='replace')).get('error'):
            angles.append(barcode.orientation)
    if not angles:return crop,0
    angle=statistics.median(angles)
    # Multiple orientations in one crop are not permission to merge stickers.
    if any(abs(a-angle)>4 for a in angles) or abs(angle)>15:return crop,0
    if abs(angle)<1:return crop,0
    from PIL import Image
    return crop.rotate(angle,resample=Image.Resampling.BICUBIC,expand=True,fillcolor='white'),angle


def uncovered_symbols(symbols, regions):
    """Count physical positions, never distinct GTIN/REF identities."""
    return [s for s in symbols if not any(r['bbox'][0]<=s['center'][0]<=r['bbox'][2]
            and r['bbox'][1]<=s['center'][1]<=r['bbox'][3] for r in regions)]
