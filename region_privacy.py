"""Local, fail-closed product-region gate. No network or persistence.

Full-page OCR is local only. External services receive a canvas containing only
validated product regions; header extraction by a remote model is forbidden.
"""
import re
from PIL import Image, ImageDraw, ImageOps

PRIVATE = re.compile(r'pazient|patient|cartella|clinic(?:al)?\s*record|data\s*(?:impianto|intervento)|prodotti\s*impiantati|\bdata\b|\bimpianto\b|\bprodotti\b|\bresp\b|firma|signature', re.I)
PRODUCT = re.compile(r'\bREF\b|\bLOT\b|\(01\)\s*\d{14}|\b\d{2}\.\d{3}\.\d{3}(?:TS|S)\b|\b\d{3}\.\d{3}(?:TS|S)\b|\b(?!20\d{2}-)\d{4}-\d{2,6}(?:-\d{2,3})?\b', re.I)
BRAND = re.compile(r'depuy|synthes|attune|smartset|velys',re.I)


def local_words(page):
    import shutil
    if not shutil.which("tesseract"):
        raise RuntimeError("Filtro privacy locale non disponibile: nessun invio esterno consentito")
    import cv2
    import numpy as np
    from linear_label_geometry import _words
    image=page.copy(); image.thumbnail((3600,3600))
    gray=cv2.cvtColor(np.asarray(image.convert('RGB')),cv2.COLOR_RGB2GRAY)
    enhanced=Image.fromarray(cv2.createCLAHE(clipLimit=2,tileGridSize=(16,16)).apply(gray))
    binary=Image.fromarray(cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,61,12))
    words=_words(image)+_words(enhanced)+_words(binary)
    return [dict(w,x=w['x']/image.width*1000,y=w['y']/image.height*1000,
                 w=w['w']/image.width*1000,h=w['h']/image.height*1000) for w in words]


def private_bands(words):
    # Do not retain the text or a photograph of a private line in extraction JSON.
    bands=[]
    for word in words:
        if PRIVATE.search(word['text']):
            bands.append([0,max(0,word['y']-3),1000,min(1000,word['y']+word['h']+12)])
    return bands


def intersects(a,b):
    return min(a[2],b[2])>max(a[0],b[0]) and min(a[3],b[3])>max(a[1],b[1])


def text_in(words,box):
    return ' '.join(w['text'] for w in words if box[0]<=w['x']+w['w']/2<=box[2] and box[1]<=w['y']+w['h']/2<=box[3])


def contrast_regions(page):
    """Measure light rectangular patches on darker paper, including tilted labels."""
    import cv2
    import numpy as np
    image=page.copy();image.thumbnail((1800,1800))
    gray=cv2.cvtColor(np.asarray(image.convert('RGB')),cv2.COLOR_RGB2GRAY)
    candidates=[]
    for threshold in range(100,241,5):
        for exclude_white_border in (False,True):
            mask=(gray>threshold)&((gray<245) if exclude_white_border else True)
            binary=mask.astype('uint8')*255
            contours=[]
            for variant in (binary,cv2.morphologyEx(binary,cv2.MORPH_OPEN,np.ones((5,5),np.uint8))):
                found,_=cv2.findContours(variant,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
                contours.extend(found)
            for c in contours:
                rect=cv2.minAreaRect(c);w,h=rect[1]
                if min(w,h)<28 or not 1.8<max(w,h)/min(w,h)<5 or not .002<w*h/(image.width*image.height)<.065:
                    continue
                if cv2.contourArea(c)/max(1,w*h)<.72:continue
                x,y,bw,bh=cv2.boundingRect(c)
                # Contrast against the surrounding paper, not scanner white margins.
                ring=gray[max(0,y-8):min(image.height,y+bh+8),max(0,x-8):min(image.width,x+bw+8)]
                inner=gray[y:y+bh,x:x+bw]
                if float(np.percentile(inner,80))-float(np.percentile(ring,20))<12:continue
                box=[max(0,round(x/image.width*1000)-1),max(0,round(y/image.height*1000)-1),
                     min(1000,round((x+bw)/image.width*1000)+1),min(1000,round((y+bh)/image.height*1000)+1)]
                candidates.append({'bbox':box,'rotation':0,'geometry_source':'local_contrast_patch','patch_area':w*h})
    # Prefer complete measured stickers over partial segmentation of one end.
    import statistics
    lengths=[r['bbox'][2]-r['bbox'][0] for r in candidates]
    typical=statistics.median(lengths) if lengths else 0
    if len(candidates)>=6:
        candidates=[r for r in candidates if r['bbox'][2]-r['bbox'][0] <= typical*1.5]
    output=[]
    for r in sorted(candidates,key=lambda r:r['patch_area'],reverse=True):
        from label_pipeline import overlap
        if not any(overlap(r['bbox'],o['bbox'])>.65 for o in output):output.append(r)
    return output


def safe_product_regions(page, anchors=()):
    """Return safe accepted and recoverable regions; private candidates disappear."""
    from label_pipeline import crop_region,decode_barcodes,overlap
    words=local_words(page); blocked=private_bands(words)
    text=' '.join(w['text'] for w in words)
    # A dedicated landscape photograph of one branded product label needs no
    # template offset, which can cut the REF off very small source images.
    if not blocked and 2<page.width/page.height<5 and BRAND.search(text):
        if PRODUCT.search(text) or any(not b.get('error') and b.get('gtin') for b in decode_barcodes(page)):
            return [{'bbox':[0,0,1000,1000],'rotation':0,
                     'geometry_source':'local_single_product','local_product_signal':True}],[]
    ordered=sorted(anchors,key=lambda r:0 if r.get('geometry_source')=='local_linear_barcodes' else 1)
    if sum(r.get('geometry_source')=='local_linear_barcodes' for r in ordered)>=3:
        ordered=[r for r in ordered if r.get('geometry_source')=='local_linear_barcodes']
    patches=contrast_regions(page)
    if sum(r.get('geometry_source')=='local_datamatrix_sticker' for r in ordered)>=3:
        ordered=[r for r in ordered if r.get('geometry_source')=='local_datamatrix_sticker']
    elif len(patches)>=3 and not any(r.get('geometry_source')=='local_linear_barcodes' for r in ordered):
        ordered=[]  # Measured sticker edges outrank template guesses on gray forms.
    # Repair a template cropped short at the printed REF end using measured paper edges.
    from label_pipeline import overlap
    refined=[]
    for region in ordered:
        box=region['bbox']; repaired=dict(region)
        if region.get('geometry_source')=='local_datamatrix_sticker':
            for patch in patches:
                b=patch['bbox']
                if (overlap(box,b)>.65 and b[2]-b[0]>(box[2]-box[0])*1.15
                        and .75<(b[3]-b[1])/max(1,box[3]-box[1])<1.25):
                    repaired['bbox']=[min(box[0],b[0]),min(box[1],b[1]),max(box[2],b[2]),max(box[3],b[3])]
                    break
        refined.append(repaired)
    candidates=(refined+patches)[:96]
    accepted=[];rejected=[]
    for r in candidates:
        box=r['bbox']
        if any(intersects(box,b) for b in blocked):continue
        text=text_in(words,box)
        if re.search(r'\bspazio\b|\bpatch\b',text,re.I):continue
        # A physical patch or product field is required before making a crop.
        if not (r.get('geometry_source')=='local_contrast_patch' or r.get('geometry_source') in {'local_datamatrix_sticker','local_datamatrix_finder','local_linear_barcodes'} or PRODUCT.search(text) or BRAND.search(text)):
            continue
        if any(overlap(box,o['bbox'])>.65 for o in accepted+rejected):continue
        crop=crop_region(page,box).rotate(r.get('rotation',0),expand=True,fillcolor='white')
        decoded=decode_barcodes(crop)
        from linear_label_geometry import _words
        # This local read operates only after private-line rejection.
        readable=ImageOps.autocontrast(crop.convert('L')).resize((crop.width*2,crop.height*2))
        local_text=' '.join(w['text'] for image,psm in ((crop,11),(readable,11),(readable,6)) for w in _words(image,psm))
        if not (PRODUCT.search(local_text) or BRAND.search(local_text)):
            binary=crop.convert('L').point(lambda p:255 if p>120 else 0).resize((crop.width*3,crop.height*3))
            local_text+=' '+' '.join(w['text'] for angle in (-10,-15,90,180,270) for w in _words(binary.rotate(angle,expand=True,fillcolor=255)))
        evidence=bool(any(not b.get('error') for b in decoded) or PRODUCT.search(text+' '+local_text) or BRAND.search(text+' '+local_text))
        entry=dict(r,local_product_signal=evidence)
        (accepted if evidence else rejected).append(entry)
    return sorted(accepted,key=lambda r:(r['bbox'][1],r['bbox'][0])), rejected


def product_canvas(page,regions):
    """Only locally approved product pixels can cross the service boundary."""
    canvas=Image.new('RGB',page.size,'white')
    for r in regions:
        box=tuple(round(v*(page.width if i%2==0 else page.height)/1000) for i,v in enumerate(r['bbox']))
        canvas.paste(page.crop(box),box[:2])
    return canvas
