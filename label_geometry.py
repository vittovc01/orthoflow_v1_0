"""Local Synthes label geometry from DataMatrix finder edges, not REF identity.

The finder is a physical anchor even when its payload cannot be decoded. Template
proportions are estimated from visible sticker rectangles. Operator count review
remains necessary for stickers without readable finder patterns or other layouts.
"""
import math

from PIL import Image


def _ordered_quad(points, center, np):
    points = points[np.argsort(np.arctan2(points[:,1]-center[1],points[:,0]-center[0]))]
    return np.roll(points, -np.argmin(points.sum(axis=1)), axis=0).astype('float32')


def finder_orientation(top, bottom, left, right):
    # The Synthes stickers in this supported layout have the upright finder at
    # bottom-left. Lack of a solid-vs-timing edge distinction is not evidence.
    if abs(bottom-top) < .15 or abs(right-left) < .12:
        return None
    if bottom > top:
        return (-1,0,0) if left > right else (0,1,270)
    return (0,-1,90) if left > right else (1,0,180)


def _locate_in_orientation(page):
    try:
        import cv2
        import numpy as np
    except ImportError:
        return []
    scale = min(1.0, 2200 / max(page.size))
    image = page.resize(tuple(max(1,round(v*scale)) for v in page.size))
    arr = np.asarray(image.convert('RGB'))
    gray = cv2.cvtColor(arr,cv2.COLOR_RGB2GRAY)
    lab_b = cv2.cvtColor(arr,cv2.COLOR_RGB2LAB)[:,:,2]
    area = image.width * image.height
    rectangles = []
    for threshold in (128,130,132):
        contours,_ = cv2.findContours((lab_b>threshold).astype('uint8')*255,
                                      cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            rect = cv2.minAreaRect(contour)
            w,h = rect[1]
            if min(w,h)>25 and 2<max(w,h)/min(w,h)<4.5 and .005<w*h/area<.035 and cv2.contourArea(contour)/(w*h)>.65:
                rectangles.append(rect)
    long_side = float(np.median([max(r[1]) for r in rectangles])) if rectangles else None
    short_side = float(np.median([min(r[1]) for r in rectangles])) if rectangles else None
    mask = cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY_INV,31,9)
    mask = cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    contours,_ = cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    seeds = []
    for contour in contours:
        rect = cv2.minAreaRect(contour)
        w,h = rect[1]
        if not (20<min(w,h) and max(w,h)<55 and min(w,h)/max(w,h)>.7 and cv2.contourArea(contour)/(w*h)>.6):
            continue
        quad = _ordered_quad(cv2.boxPoints(rect),rect[0],np)
        dest = np.array([[0,0],[63,0],[63,63],[0,63]],dtype='float32')
        finder = cv2.warpPerspective(gray,cv2.getPerspectiveTransform(quad,dest),(64,64))
        dark = cv2.threshold(finder,0,255,cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)[1]/255
        orientation = finder_orientation(dark[:4].mean(),dark[-4:].mean(),
                                          dark[:,:4].mean(),dark[:,-4:].mean())
        if orientation:
            seeds.append((rect,orientation))
    if len(seeds)>64:
        return []  # Dense texture is not a trustworthy label layout.
    regions=[]
    for rect,(dx,dy,rotation) in seeds:
        cx,cy = rect[0]
        length = long_side or max(rect[1])*9
        width = short_side or max(rect[1])*3
        center = (cx+dx*length*.42,cy+dy*length*.42)
        bw,bh = (length*1.08,width*1.15) if dx else (width*1.15,length*1.08)
        x,y,xx,yy = [round(v) for v in (center[0]-bw/2,center[1]-bh/2,
                                       center[0]+bw/2,center[1]+bh/2)]
        x,y,xx,yy = max(0,x),max(0,y),min(image.width,xx),min(image.height,yy)
        roi = lab_b[y:yy,x:xx]
        local=[]
        for threshold in (128,130):
            contours,_ = cv2.findContours((roi>threshold).astype('uint8')*255,
                                          cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                r = cv2.minAreaRect(contour)
                w,h = r[1]
                if min(w,h)>width*.65 and max(w,h)>length*.75 and cv2.contourArea(contour)/(w*h)>.65 and cv2.pointPolygonTest(contour,(cx-x,cy-y),False)>=0:
                    local.append((cv2.contourArea(contour),r))
        if local:
            r = max(local,key=lambda v:v[0])[1]
            points = cv2.boxPoints(r)+np.array([x,y])
            lo,hi = points.min(axis=0)-3,points.max(axis=0)+3
            # Partial colour segmentation must never shorten the REF end.
            if max(r[1]) < length*.9:
                if dx:
                    y,yy = math.floor(lo[1]),math.ceil(hi[1])
                else:
                    x,xx = math.floor(lo[0]),math.ceil(hi[0])
            else:
                x,y,xx,yy = math.floor(lo[0]),math.floor(lo[1]),math.ceil(hi[0]),math.ceil(hi[1])
        x,y,xx,yy = max(0,x),max(0,y),min(image.width,xx),min(image.height,yy)
        # Exclude even a partial neighbouring finder, not just its centre.
        for other,_ in seeds:
            if other is rect:
                continue
            points = cv2.boxPoints(other)
            ox,oy = points.min(axis=0)
            oxx,oyy = points.max(axis=0)
            if ox<xx and oxx>x and oy<yy and oyy>y:
                if oxx<cx and ox<=x:
                    x=max(x,math.ceil(oxx)+2)
                elif ox>cx and oxx>=xx:
                    xx=min(xx,math.floor(ox)-2)
                elif oyy<cy and oy<=y:
                    y=max(y,math.ceil(oyy)+2)
                elif oy>cy and oyy>=yy:
                    yy=min(yy,math.floor(oy)-2)
        other_finders = sum(1 for rr,_ in seeds if x<rr[0][0]<xx and y<rr[0][1]<yy)
        if other_finders != 1:
            continue
        regions.append({'bbox':[round(x/image.width*1000),round(y/image.height*1000),
                                round(xx/image.width*1000),round(yy/image.height*1000)],
                        'rotation':rotation,'finder_bbox':[round(v/(image.width if i%2==0 else image.height)*1000)
                            for i,v in enumerate((cx-rect[1][0]/2,cy-rect[1][1]/2,
                                                  cx+rect[1][0]/2,cy+rect[1][1]/2))],
                        'geometry_source':'local_datamatrix_finder'})
    return regions


def locate_datamatrix_labels(page):
    """Repeat in a second orientation; deduplicate physical finders, not REF/lot."""
    regions=[]
    for turn in (0,90):
        for region in _locate_in_orientation(page.rotate(turn,expand=True)):
            if turn:
                for key in ('bbox','finder_bbox'):
                    b=region[key]
                    region[key]=[1000-b[3],b[0],1000-b[1],b[2]]
                region['rotation']=(region['rotation']+turn)%360
            box=region['finder_bbox']
            duplicate=False
            for previous in regions:
                other=previous['finder_bbox']
                intersection=max(0,min(box[2],other[2])-max(box[0],other[0]))*max(0,min(box[3],other[3])-max(box[1],other[1]))
                area=min((box[2]-box[0])*(box[3]-box[1]),(other[2]-other[0])*(other[3]-other[1]))
                if area>0 and intersection/area>.65:
                    duplicate=True
                    break
            if not duplicate:
                regions.append(region)
    return regions
