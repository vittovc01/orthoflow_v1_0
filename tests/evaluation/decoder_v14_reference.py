"""Frozen PR39 decoder for controlled same-ROI comparisons only. Not production."""
from PIL import Image
from label_pipeline import gs1_parse

def decode_barcodes(image):
    import zxingcpp
    results = []
    # Retry conservative threshold/scale variants; retain every distinct payload.
    variants = [image]
    gray = image.convert('L')
    variants += [gray.point(lambda p: 255 if p > t else 0) for t in (60, 80, 120, 160)]
    small = gray.resize((max(1, round(gray.width*.75)), max(1, round(gray.height*.75))), Image.Resampling.LANCZOS)
    variants.append(small.point(lambda p: 255 if p > 80 else 0))
    # Resampling must be explicit: default interpolation can destroy a finder
    # whose module boundary falls between pixels. Never invent a payload.
    if max(gray.size) < 1200:
        variants.append(gray.resize(tuple(round(v*1.5) for v in gray.size), Image.Resampling.NEAREST))
    seen = set()
    for variant in variants:
        for barcode in zxingcpp.read_barcodes(variant):
            raw = barcode.bytes.decode('utf-8', errors='replace')
            symbology = getattr(barcode, 'symbology_identifier', '')
            if raw in seen:
                continue
            if symbology in {']d2', ']C1'} or raw.startswith((']d2', ']C1', '(01)')):
                seen.add(raw)
                results.append({'raw': raw, 'format': str(barcode.format), **gs1_parse(raw)})
    return results

