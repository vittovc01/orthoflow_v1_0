"""Bounded non-generative ZXing retries. Pixel resampling never adds evidence.

Every result must pass the existing GS1 parser. No payload reconstruction,
checksum repair or character substitution is performed.
"""
import math
from PIL import Image, ImageOps


def decode(image):
    import cv2
    import numpy as np
    import zxingcpp
    from label_pipeline import gs1_parse
    found={}
    def read(arr,method,pure=False):
        for b in zxingcpp.read_barcodes(arr,try_rotate=True,try_downscale=False,is_pure=pure):
            raw=b.bytes.decode('utf-8',errors='replace')
            if getattr(b,'symbology_identifier','') not in {']d2',']C1'} and not raw.startswith((']d2',']C1','(01)')):continue
            parsed=gs1_parse(raw)
            # Invalid payloads are preserved as explicit errors, never trusted.
            found.setdefault(raw,dict(raw=raw,format=str(b.format),decode_method=method,**parsed))
    gray=np.asarray(image.convert('L'))
    read(gray,'native')
    # First try native thresholds: do not destroy original modules by smoothing.
    for t in (60,80,120,160):read(np.where(gray>t,255,0).astype('uint8'),f'global:{t}')
    if any(not b.get('error') for b in found.values()):return list(found.values())
    # Bounded label crops only, so scaled retries cannot allocate page-size arrays.
    work=image.convert('L').copy();work.thumbnail((1400,1400))
    g=np.asarray(work)
    clahe=cv2.createCLAHE(clipLimit=2.0,tileGridSize=(8,8)).apply(g)
    variants=[('gray',g),('clahe',clahe),('otsu',cv2.threshold(g,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)[1])]
    for block in (11,21,31):
        variants.append((f'adaptive:{block}',cv2.adaptiveThreshold(g,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,block,5)))
    for scale in (.75,1.5,2,3,4):
        for name,arr in variants:
            if max(arr.shape)*scale>4200:continue
            enlarged=cv2.resize(arr,None,fx=scale,fy=scale,interpolation=cv2.INTER_NEAREST if scale>=1 else cv2.INTER_AREA)
            read(enlarged,f'{name}:scale:{scale}')
        if any(not b.get('error') for b in found.values()):return list(found.values())
    # Adaptive threshold and nearest-neighbour sampling depend on pixel phase.
    # Rotate the SOURCE before binarizing/resampling, not only the result.
    for turn in (1,2,3):
        rotated=np.ascontiguousarray(np.rot90(g,turn))
        for scale in (.75,1.5,2,3,4):
            for block in (11,21,31):
                binary=cv2.adaptiveThreshold(rotated,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,block,5)
                arr=cv2.resize(binary,None,fx=scale,fy=scale,interpolation=cv2.INTER_NEAREST if scale>=1 else cv2.INTER_AREA)
                read(arr,f'rotation:{turn*90}:adaptive:{block}:scale:{scale}')
            if any(not b.get('error') for b in found.values()):return list(found.values())
    # Small tilt and cardinal rotation retry. No destructive erosion/dilation.
    for angle in (-8,-4,4,8,90,180,270):
        rotated=work.rotate(angle,expand=True,resample=Image.Resampling.BICUBIC,fillcolor=255)
        read(np.asarray(rotated.resize(tuple(v*3 for v in rotated.size),Image.Resampling.NEAREST)),f'rotation:{angle}:scale:3')
        if any(not b.get('error') for b in found.values()):return list(found.values())
    # Rectify measured near-square finder components. These are decoding ROIs,
    # never item identities or grounds to count a physical label.
    mask=cv2.adaptiveThreshold(g,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY_INV,21,5)
    contours,_=cv2.findContours(mask,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    candidates=[]
    for c in contours:
        rect=cv2.minAreaRect(c);w,h=rect[1]
        if min(w,h)<12 or max(w,h)>min(260,max(g.shape)*.7) or min(w,h)/max(w,h)<.7:continue
        if cv2.contourArea(c)/(w*h)<.35:continue
        candidates.append(rect)
    for rect in sorted(candidates,key=lambda r:r[1][0]*r[1][1],reverse=True)[:12]:
        points=cv2.boxPoints(rect);center=points.mean(axis=0)
        points=points[np.argsort(np.arctan2(points[:,1]-center[1],points[:,0]-center[0]))]
        points=np.roll(points,-np.argmin(points.sum(axis=1)),axis=0).astype('float32')
        size=round(max(rect[1]));dest=np.array([[0,0],[size-1,0],[size-1,size-1],[0,size-1]],dtype='float32')
        square=cv2.warpPerspective(g,cv2.getPerspectiveTransform(points,dest),(size,size),borderValue=255)
        for scale in (2,4):
            roi=cv2.copyMakeBorder(cv2.resize(square,None,fx=scale,fy=scale,interpolation=cv2.INTER_NEAREST),12,12,12,12,cv2.BORDER_CONSTANT,value=255)
            read(roi,f'perspective:scale:{scale}',pure=True)
        if any(not b.get('error') for b in found.values()):return list(found.values())
    return list(found.values())
