"""Conservative acquisition warnings. Heuristic flags, not a certified quality score."""

def inspect_quality(image):
    try:
        import cv2
        import numpy as np
    except ImportError:
        return {'conditions':[],'issues':['Controllo qualità immagine non disponibile'],'available':False}
    sample=image.convert('L');sample.thumbnail((512,512))
    gray=np.asarray(sample)
    mean=float(gray.mean());contrast=float(gray.std())
    sharpness=float(cv2.Laplacian(gray,cv2.CV_64F).var())
    bright=gray>=250;fraction=float(bright.mean())
    conditions=[]
    if mean<65:conditions.append('dark')
    if sharpness<35 and contrast>3:conditions.append('blur')
    if .02<fraction<.35:
        count,_,stats,_=cv2.connectedComponentsWithStats(bright.astype('uint8'))
        if any(s[cv2.CC_STAT_AREA]>gray.size*.025 for s in stats[1:]):
            conditions.append('glare')
    messages={'dark':'Foto poco luminosa: verificare il testo o acquisire una nuova foto',
              'blur':'Foto sfocata: verificare il testo o acquisire una nuova foto',
              'glare':'Possibile riflesso o zona satura: verificare che non copra il testo'}
    return {'available':True,'conditions':conditions,'issues':[messages[c] for c in conditions],
            'mean_brightness':mean,'laplacian_variance':sharpness,'saturated_fraction':fraction}


def geometry_alerts(regions):
    """Warnings from measured regions, not a claim to see hidden label portions."""
    warnings=[]
    for r in regions:
        if abs(r.get('deskew_angle') or 0)>5:
            warnings.append('Etichetta inclinata: raddrizzamento geometrico applicato')
    for i,a in enumerate(regions):
        ax,ay,ar,ab=a['bbox']
        for b in regions[i+1:]:
            bx,by,br,bb=b['bbox']
            width=min(ar,br)-max(ax,bx);height=min(ab,bb)-max(ay,by)
            if width>0 and height>0:
                fraction=width*height/max(1,min((ar-ax)*(ab-ay),(br-bx)*(bb-by)))
                if fraction>.15:warnings.append('Possibili etichette sovrapposte o ritagli misti: verificare i confini')
            elif (width>0 and abs(height)<=3) or (height>0 and abs(width)<=3):
                warnings.append('Etichette che si toccano: verificare i confini e il conteggio')
    return list(dict.fromkeys(warnings))
