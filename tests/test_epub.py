import zipfile
from pathlib import Path

from pdf2epub.blocks import Block, Chapter
from pdf2epub.epub import write_epub


def test_epub_package_shape(tmp_path: Path):
    image = _png()
    chapter = Chapter(
        title="Chapter One",
        filename="chapter-01.xhtml",
        blocks=[
            Block("heading", text="Chapter One", level=1, source="outline"),
            Block("paragraph", text="Hello & welcome."),
            Block("list_item", text="First"),
            Block("list_item", text="Second"),
            Block("figure", image=image, image_ext="png", caption="A figure", alt="A figure"),
        ],
    )
    dest = tmp_path / "book.epub"
    write_epub(dest, [chapter], title="Sample", language="en", author="Ada")
    with zipfile.ZipFile(dest) as archive:
        names = archive.namelist()
        assert names[0] == "mimetype"
        info = archive.getinfo("mimetype")
        assert info.compress_type == zipfile.ZIP_STORED
        assert archive.read("mimetype") == b"application/epub+zip"
        opf = archive.read("OEBPS/content.opf").decode("utf-8")
        nav = archive.read("OEBPS/nav.xhtml").decode("utf-8")
        html = archive.read("OEBPS/chapter-01.xhtml").decode("utf-8")
        css = archive.read("OEBPS/style.css").decode("utf-8")
    assert 'version="3.0"' in opf
    assert "<dc:title>Sample</dc:title>" in opf
    assert "<dc:language>en</dc:language>" in opf
    assert 'property="dcterms:modified"' in opf
    assert 'properties="nav"' in opf
    assert "image/png" in opf
    assert 'epub:type="toc"' in nav
    assert "Hello &amp; welcome." in html
    assert "<ul>" in html
    assert "<figcaption>A figure</figcaption>" in html
    assert "direction" not in css.lower()
    assert "&" not in css


def _png() -> bytes:
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (40, 40), "white").save(buffer, format="PNG")
    return buffer.getvalue()
