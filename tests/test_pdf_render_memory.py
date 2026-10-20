"""Memory-safe rendering contracts, using synthetic PDFs without clinical data."""
from io import BytesIO
from types import SimpleNamespace

import fitz
import pytest
from PIL import Image

from label_pipeline import MAX_RENDER_PIXELS, iter_pages, pdf_render_scale, render_pages


def test_large_page_scan_keeps_native_pixels_instead_of_sixteenfold_enlargement(tmp_path):
    buffer = BytesIO()
    image = Image.new('RGB', (2448, 3264), 'white')
    image.save(buffer, format='JPEG')
    image.close()
    path = tmp_path/'scan.pdf'
    with fitz.open() as doc:
        page = doc.new_page(width=2448, height=3316)
        page.insert_image(fitz.Rect(0, 0, 2448, 3264), stream=buffer.getvalue())
        doc.save(path)
    pages = render_pages(path)
    try:
        assert pages[0].size == (2448, 3316)
        assert pages[0].width * pages[0].height == 8_117_568
        assert pages[0].width * pages[0].height * 16 == 129_881_088
    finally:
        for page in pages:
            page.close()


@pytest.mark.parametrize('size', [(10000,15000), (10000000,10000000), (10000000,1)])
def test_pixel_limit_is_chosen_before_rendering_even_for_extreme_page_sizes(size):
    import math
    page = SimpleNamespace(rect=fitz.Rect(0,0,*size), get_image_info=lambda:[])
    scale = pdf_render_scale(page)
    assert math.ceil(size[0]*scale) * math.ceil(size[1]*scale) <= MAX_RENDER_PIXELS
    assert max(size)*scale <= 65500


def test_regular_vector_a4_keeps_existing_288_dpi_resolution():
    page = SimpleNamespace(rect=fitz.Rect(0,0,595,842), get_image_info=lambda:[])
    assert pdf_render_scale(page) == 4


def test_pdf_iterator_does_not_render_later_pages_until_requested(tmp_path, monkeypatch):
    path = tmp_path/'pages.pdf'
    with fitz.open() as doc:
        doc.new_page(width=100,height=100)
        doc.new_page(width=100,height=100)
        doc.save(path)
    calls = []
    original = fitz.Page.get_pixmap
    def record(page, **kwargs):
        calls.append(page.number)
        return original(page, **kwargs)
    monkeypatch.setattr(fitz.Page, 'get_pixmap', record)
    iterator = iter_pages(path)
    assert not calls
    first = next(iterator)
    assert calls == [0]
    first.close()
    second = next(iterator)
    assert calls == [0,1]
    second.close()
    iterator.close()


def test_duplicate_check_closes_all_rasters_before_calling_analyzer(monkeypatch):
    from ocr_repository import OriginalDocument
    from ocr_service import analyze_documents
    opened = []
    def pages(_):
        for _ in range(2):
            page = Image.new('RGB',(30,40),'white')
            opened.append(page)
            yield page
    monkeypatch.setattr('label_pipeline.iter_pages', pages)
    def analyze(*args, **kwargs):
        assert len(opened) == 2
        for page in opened:
            with pytest.raises(ValueError):
                page.getpixel((0,0))
        return {'items':[]}
    buffer = BytesIO()
    Image.new('RGB',(10,10),'white').save(buffer,format='PNG')
    result = analyze_documents([OriginalDocument('scan.png',buffer.getvalue())],analyzer=analyze)
    assert result['documents'][0]['status'] == 'analyzed'
