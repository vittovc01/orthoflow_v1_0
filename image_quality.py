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


def acquisition_report(page,regions):
    """Provisional acquisition targets, not a proven decoder accuracy threshold.

    A missing EXIF field does not establish resizing/compression. JPEG encoding
    alone does not establish excessive lossy compression either.
    """
    warnings=[];longest=max(page.size)
    if longest<2400:
        warnings.append(f'Risoluzione {page.width}×{page.height}: sotto il target provvisorio di 2400 px sul lato lungo; acquisire etichette più ravvicinate')
    symbols=[]
    for r in regions:
        b=r.get('finder_bbox')
        if b:symbols.append(min((b[2]-b[0])*page.width/1000,(b[3]-b[1])*page.height/1000))
    if symbols and min(symbols)<64:
        warnings.append(f'DataMatrix più piccolo circa {min(symbols):.0f} px: sotto il target provvisorio di 64 px; nuova foto ravvicinata richiesta')
    exif=page.getexif()
    source=page.info.get('_ocr_source_exif',{})
    original_w=exif.get(40962) or source.get('40962');original_h=exif.get(40963) or source.get('40963')
    metadata_resized=bool(original_w and original_h and (original_w>page.width or original_h>page.height))
    if metadata_resized:warnings.append('Dimensioni inferiori a quelle EXIF: immagine probabilmente ridimensionata')
    software=str(exif.get(305,'') or source.get('305','')).lower()
    if any(s in software for s in ('whatsapp','screenshot','screen capture')):
        warnings.append('Metadati di messaggistica/screenshot: possibile ridimensionamento o ricompressione; usare il file originale')
    quant=getattr(page,'quantization',None) or page.info.get('_ocr_source_quantization')
    if quant and sum(sum(v) for v in quant.values())/max(1,sum(len(v) for v in quant.values()))>35:
        warnings.append('Quantizzazione JPEG elevata: possibile forte compressione; usare il file originale')
    return {'width':page.width,'height':page.height,'finder_sides_px':[round(x,1) for x in symbols],
            'minimum_long_side_target':2400,'symbol_side_target':64,'threshold_status':'provisional_not_validated',
            'resized_metadata':metadata_resized,'warnings':warnings}
