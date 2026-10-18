"""Conservative archive compression, shared by desktop and mobile uploads.
Never change dimensions, PDF pages, text, annotations or signed PDF bytes.
"""
import io
import re
import time
from dataclasses import dataclass
from pathlib import Path
from PIL import Image, ImageOps
from pypdf import PdfReader, PdfWriter

MAX_SYNC_BYTES = 8 * 1024 * 1024
MAX_SYNC_IMAGE_PIXELS = 12_000_000
MAX_PDF_PAGES = 60


@dataclass(frozen=True)
class CompressedDocument:
    data: bytes
    content_type: str
    original_bytes: int
    method: str
    elapsed_ms: float = 0.0

    @property
    def saved_bytes(self):
        return self.original_bytes - len(self.data)


def compress_document(data, filename='', content_type=None):
    """Keep interactive compression bounded; upload large inputs unchanged."""
    started = time.perf_counter()
    mime = content_type or {'.pdf':'application/pdf','.png':'image/png',
        '.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp'}.get(
            Path(filename).suffix.lower(), 'application/octet-stream')

    def result(payload=data, method='original'):
        return CompressedDocument(
            payload, mime, len(data), method,
            round((time.perf_counter() - started) * 1000, 2))

    if not data:
        return result()
    if len(data) > MAX_SYNC_BYTES:
        return result(method='original_sync_limit')
    try:
        if data.startswith(b'%PDF-'):
            mime = 'application/pdf'
            if re.search(rb'/(?:ByteRange|FT\s*/Sig|Type\s*/Sig)\b', data):
                return result(method='signed_pdf_preserved')
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                return result()
            if not 1 <= len(reader.pages) <= MAX_PDF_PAGES:
                return result(method='original_sync_limit' if len(reader.pages) > MAX_PDF_PAGES else 'original')
            fields = reader.get_fields() or {}
            if any(f.get('/FT') == '/Sig' for f in fields.values()):
                return result(method='signed_pdf_preserved')
            writer = PdfWriter(clone_from=reader)
            for page in writer.pages:
                page.compress_content_streams(level=9)
            writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=False)
            out = io.BytesIO()
            writer.write(out)
            payload = out.getvalue()
            if len(PdfReader(io.BytesIO(payload)).pages) != len(reader.pages):
                return result()
            return result(payload, 'pdf_lossless') if len(payload) < len(data) else result()

        with Image.open(io.BytesIO(data)) as image:
            pixels = image.width * image.height
            if pixels > MAX_SYNC_IMAGE_PIXELS:
                return result(method='original_sync_limit')
            if getattr(image, 'n_frames', 1) != 1:
                return result()
            kind = image.format
            out = io.BytesIO()
            if kind == 'JPEG':
                mime = 'image/jpeg'
                image = ImageOps.exif_transpose(image)
                image.convert('RGB').save(out, 'JPEG', quality=88, subsampling=0, optimize=True)
                method = 'jpeg_quality_88'
            elif kind == 'PNG':
                mime = 'image/png'
                image.save(out, 'PNG', optimize=True, compress_level=9)
                method = 'png_lossless'
            else:
                return result()
            payload = out.getvalue()
            return result(payload, method) if len(payload) < len(data) else result()
    except Exception:
        return result()
