"""Conservative archive compression, shared by desktop and mobile uploads.
Never change dimensions, PDF pages, text, annotations or signed PDF bytes.
"""
import io
import re
from dataclasses import dataclass
from pathlib import Path
from PIL import Image, ImageOps
from pypdf import PdfReader, PdfWriter


@dataclass(frozen=True)
class CompressedDocument:
    data: bytes
    content_type: str
    original_bytes: int
    method: str

    @property
    def saved_bytes(self):
        return self.original_bytes - len(self.data)


def compress_document(data, filename='', content_type=None):
    """Keep the original when unsupported, signed, protected or not smaller.
    JPEG is re-encoded at quality 88 with full chroma resolution; PNG/PDF lossless.
    Validation/rejection of input belongs to the upload flow, not this optimiser.
    """
    mime = content_type or {'.pdf':'application/pdf','.png':'image/png',
        '.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp'}.get(Path(filename).suffix.lower(), 'application/octet-stream')
    def result(payload=data, method='original'):
        return CompressedDocument(payload, mime, len(data), method)
    if not data or len(data) > 20 * 1024 * 1024:
        return result()
    try:
        if data.startswith(b'%PDF-'):
            mime = 'application/pdf'
            # Any signature field / byte range: preserve entire source, including revisions.
            if re.search(rb'/(?:ByteRange|FT\s*/Sig|Type\s*/Sig)\b', data):
                return result(method='signed_pdf_preserved')
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted or not 1 <= len(reader.pages) <= 100:
                return result()
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
            if image.width * image.height > 40_000_000 or getattr(image, 'n_frames', 1) != 1:
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
        # Optimisation must never cause document loss or block a previously valid upload.
        return result()
