"""Refine Synthes finder anchors using measured sticker edges, never identity text."""
import math
import statistics


def refine_sticker_edges(page, regions):
    if len(regions) < 3:
        return regions
    try:
        import cv2
        import numpy as np
    except ImportError:
        return regions
    scale = min(1.0, 1800 / max(page.size))
    image = page.resize(tuple(max(1, round(v * scale)) for v in page.size))
    width, height = image.size
    anchors = []
    for region in regions:
        b = region['finder_bbox']
        anchors.append(((b[0]+b[2])*width/2000, (b[1]+b[3])*height/2000,
                        max((b[2]-b[0])*width/1000, (b[3]-b[1])*height/1000)))
    blur = max(3, round(statistics.median(a[2] for a in anchors)/3) | 1)
    gray = cv2.GaussianBlur(cv2.cvtColor(np.asarray(image.convert('RGB')), cv2.COLOR_RGB2GRAY), (blur, blur), 0)
    contours = []
    for threshold in range(80, 241, 5):
        found, _ = cv2.findContours(cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)[1],
                                    cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours.extend(found)
    measured = []
    for cx, cy, size in anchors:
        candidates = []
        for contour in contours:
            rect = cv2.minAreaRect(contour)
            w, h = rect[1]
            if not (min(w,h) > size*1.8 and 2 < max(w,h)/min(w,h) < 4.5
                    and size*4.5 < max(w,h) < size*12):
                continue
            points = cv2.boxPoints(rect)
            if cv2.contourArea(contour)/(w*h) < .65 or cv2.pointPolygonTest(points, (cx,cy), False) < 0:
                continue
            # Never let a single measured sticker enclose neighbouring symbols.
            if sum(cv2.pointPolygonTest(points, (a[0],a[1]), False) >= 0 for a in anchors) != 1:
                continue
            candidates.append((w*h, rect))
        measured.append(max(candidates, key=lambda c:c[0])[1] if candidates else None)
    complete = [r for r in measured if r is not None]
    if len(complete) < 3:
        return regions
    median_length = statistics.median(max(r[1]) for r in complete)
    output = []
    for region, anchor, rect in zip(regions, anchors, measured):
        if rect is None:
            output.append(region)
            continue
        center = np.array(rect[0], dtype=float)
        points = cv2.boxPoints(rect)
        axes = [points[1]-points[0], points[2]-points[1]]
        direction = max(axes, key=lambda v:np.linalg.norm(v))
        direction /= np.linalg.norm(direction)
        if np.dot(direction, np.array(anchor[:2])-center) < 0:
            direction = -direction
        cross = np.array([-direction[1], direction[0]])
        length, short = max(rect[1]), min(rect[1])
        # Partial white segmentation at the REF end must not truncate the header.
        extension = max(0, median_length-length) if length >= median_length*.8 else 0
        center -= direction*extension/2
        length += extension
        corners = np.array([center + direction*length*x*.52 + cross*short*y*.56
                            for x,y in ((-1,-1),(1,-1),(1,1),(-1,1))])
        lo, hi = corners.min(axis=0), corners.max(axis=0)
        bbox = [max(0, round(lo[0]/width*1000)), max(0, round(lo[1]/height*1000)),
                min(1000, round(hi[0]/width*1000)), min(1000, round(hi[1]/height*1000))]
        rotation = (round(math.degrees(math.atan2(direction[1], direction[0]))/90)*90) % 360
        output.append(dict(region, bbox=bbox, rotation=rotation,
                           deskew_angle=((math.degrees(math.atan2(direction[1], direction[0]))-rotation+180)%360)-180,
                           geometry_source='local_datamatrix_sticker'))
    return output
