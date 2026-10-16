"""DePuy linear-barcode sticker geometry; no code or lot reconstruction."""
import csv
import re
import shutil
import subprocess
from io import BytesIO

from PIL import Image


def _words(image, psm=11):
    if not shutil.which('tesseract'):
        return []
    buffer=BytesIO(); image.save(buffer,format='PNG')
    result=subprocess.run(['tesseract','stdin','stdout','--psm',str(psm),'tsv'],input=buffer.getvalue(),capture_output=True,timeout=30)
    return [dict(text=r['text'],x=int(r['left']),y=int(r['top']),w=int(r['width']),h=int(r['height']))
            for r in csv.DictReader(result.stdout.decode(errors='replace').splitlines(),delimiter='\t',quoting=csv.QUOTE_NONE) if r.get('text','').strip()]


def _ref_marker(word):
    # OCR characters locate a printed field only; NEVER become a product REF.
    if re.match(r'^20\d{2}-',word['text']):
        return False
    return 'REF' in word['text'].upper() or bool(re.match(r'^(?:\d{4}-\d{2,3}|\d{2,3}\.\d{3})',word['text']))


def locate_linear_labels(page):
    try:
        import cv2
        import numpy as np
    except ImportError:
        return []
    scaled=page.copy(); scaled.thumbnail((1800,1800))
    orientations=[]
    for angle in (0,90,180,270):
        upright=scaled.rotate(angle,expand=True)
        words=_words(upright)
        score=sum(_ref_marker(w) for w in words)
        orientations.append((score,angle,upright,words))
    score,angle,image,words=max(orientations,key=lambda r:r[0])
    if score<1:
        return []
    candidates=[_barcode_regions(image,words,angle,cv2,np,threshold,kernel)
                for threshold,kernel in ((70,(5,25)),(115,(3,15)))]
    return max(candidates,key=len)


def _barcode_regions(image,words,angle,cv2,np,threshold,kernel):
    gray=cv2.cvtColor(np.asarray(image.convert('RGB')),cv2.COLOR_RGB2GRAY)
    gx=np.abs(cv2.Sobel(gray,cv2.CV_32F,1,0,ksize=3)); gy=np.abs(cv2.Sobel(gray,cv2.CV_32F,0,1,ksize=3))
    if not gx.max():
        return []
    gradient=(gx/gx.max()*255).astype('uint8')
    mask=cv2.threshold(cv2.blur(gradient,(9,3)),threshold,255,cv2.THRESH_BINARY)[1]
    mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones(kernel,np.uint8))
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    bands=[]
    for contour in contours:
        x,y,w,h=cv2.boundingRect(contour)
        if w>image.width*.07 and 2<w/h<12 and h>20:
            coherence=gx[y:y+h,x:x+w].mean()/(gy[y:y+h,x:x+w].mean()+1)
            if coherence>2.4:
                bands.append([x,y,x+w,y+h])
    groups=[]
    for b in sorted(bands,key=lambda b:b[1]):
        matches=[]
        for i,g in enumerate(groups):
            a=g['bbox']; width=max(a[2]-a[0],b[2]-b[0])
            overlap=max(0,min(a[2],b[2])-max(a[0],b[0]))/min(a[2]-a[0],b[2]-b[0])
            gap=(b[1]+b[3]-a[1]-a[3])/2
            if overlap>.65 and 0<gap<width*.38 and b[3]-a[1]<width*.6:
                matches.append(i)
        if len(matches)==1:
            g=groups[matches[0]];a=g['bbox'];g['bbox']=[min(a[0],b[0]),min(a[1],b[1]),max(a[2],b[2]),max(a[3],b[3])];g['bands']+=1
        else:
            groups.append({'bbox':b,'bands':1})
    retained=[]
    for g in groups:
        x,y,xx,yy=g['bbox'];width=xx-x
        markers=[w for w in words if _ref_marker(w) and x-width*.12<w['x']<x+width*.65 and y-width*.55<w['y']<y]
        if g['bands']<2 and not markers and not (yy-y>width*.25 and y>image.height*.07):
            continue
        if markers:
            marker=max(markers,key=lambda w:w['y'])
            top=marker['y']-max(marker['h']*.7,width*.18)
        else:
            top=y-width*.35
        for w in words:
            if '(1/1)' in w['text'] and x-width*.12<w['x']<x+width*2.25 and top<w['y']<y:
                top=max(top,w['y']+w['h']+3)
        retained.append({'anchor':g['bbox'],'bbox':[x-width*.08,top,x+width*2.25,yy+width*.20]})
    regions=[]
    for g in retained:
        x,y,xx,yy=g['bbox'];a=g['anchor']
        for other in retained:
            if other is g:continue
            b=other['anchor']
            horizontal=max(0,min(a[2],b[2])-max(a[0],b[0]))
            if horizontal>min(a[2]-a[0],b[2]-b[0])*.65 and b[3]<a[1]:
                y=max(y,b[3]+2)
            if abs((a[1]+a[3]-b[1]-b[3])/2)<max(a[2]-a[0],b[2]-b[0])*.5 and b[0]>a[0]:
                xx=min(xx,b[0]-(b[2]-b[0])*.02)
        bbox=[round(max(0,x)/image.width*1000),round(max(0,y)/image.height*1000),round(min(image.width,xx)/image.width*1000),round(min(image.height,yy)/image.height*1000)]
        x,y,xx,yy=bbox
        if angle==90:bbox=[1000-yy,x,1000-y,xx]
        elif angle==180:bbox=[1000-xx,1000-yy,1000-x,1000-y]
        elif angle==270:bbox=[y,1000-xx,yy,1000-x]
        regions.append({'bbox':bbox,'rotation':angle,'geometry_source':'local_linear_barcodes'})
    return sorted(regions,key=lambda r:(r['bbox'][1],r['bbox'][0]))
