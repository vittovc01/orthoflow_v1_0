import io
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject, DictionaryObject, ArrayObject
from document_compression import compress_document


def pdf_fixture(signature=False):
    w=PdfWriter();page=w.add_blank_page(width=600,height=800)
    stream=DecodedStreamObject();stream.set_data(b'0 0 0 rg 1 1 10 10 re f\n'*4000)
    page[NameObject('/Contents')]=w._add_object(stream)
    if signature:
        field=DictionaryObject({NameObject('/FT'):NameObject('/Sig')})
        w._root_object[NameObject('/AcroForm')]=DictionaryObject({NameObject('/Fields'):ArrayObject([w._add_object(field)])})
    out=io.BytesIO();w.write(out);return out.getvalue()


def test_pdf_reduction_preserves_pages_and_content():
    source=pdf_fixture();result=compress_document(source,'test.pdf')
    assert len(result.data)<len(source)/4
    before=PdfReader(io.BytesIO(source));after=PdfReader(io.BytesIO(result.data))
    assert len(before.pages)==len(after.pages)==1
    assert before.pages[0].get_contents().get_data()==after.pages[0].get_contents().get_data()
    assert after.pages[0].mediabox==before.pages[0].mediabox


def test_signed_pdf_is_byte_identical():
    source=pdf_fixture(True)
    result=compress_document(source,'signed.pdf')
    assert result.data==source and result.method=='signed_pdf_preserved'
    source=pdf_fixture()+b'\n/ByteRange [0 12 30 50]'
    assert compress_document(source,'signed.pdf').data==source


def test_png_is_lossless_including_signature_alpha():
    image=Image.new('RGBA',(800,300),(255,255,255,0))
    for x in range(800):image.putpixel((x,150),(0,0,0,255))
    out=io.BytesIO();image.save(out,'PNG',compress_level=0)
    result=compress_document(out.getvalue(),'signature.png')
    assert len(result.data)<len(out.getvalue())
    restored=Image.open(io.BytesIO(result.data))
    assert restored.size==image.size and restored.tobytes()==image.tobytes()


def test_jpeg_preserves_resolution_and_remains_readable_image():
    image=Image.effect_noise((900,700),40).convert('RGB')
    out=io.BytesIO();image.save(out,'JPEG',quality=100)
    result=compress_document(out.getvalue(),'photo.jpg')
    assert result.saved_bytes>0
    assert Image.open(io.BytesIO(result.data)).size==(900,700)


def test_unsupported_or_invalid_file_never_lost():
    for source,name in [(b'not a PDF','file.pdf'),(b'PK zip source','file.xlsx')]:
        assert compress_document(source,name).data==source
