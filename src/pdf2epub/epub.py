"""Write a reflowable EPUB 3 package that follows the EPUBCheck 5.4 subset."""

import zipfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from xml.sax.saxutils import escape

from pdf2epub.blocks import Chapter
from pdf2epub.markup import STYLESHEET, chapter_xhtml, image_name, nav_xhtml

_OPF_NS = "http://www.idpf.org/2007/opf"
_DC_NS = "http://purl.org/dc/elements/1.1/"


def write_epub(
    dest: Path,
    chapters: list[Chapter],
    *,
    title: str,
    language: str,
    author: str | None = None,
    identifier: str | None = None,
) -> None:
    if not chapters:
        chapters = [Chapter(title=title or "Book", filename="chapter-01.xhtml", blocks=[])]
    book_title = title or chapters[0].title or "Book"
    lang = language or "en"
    pub_id = identifier or f"urn:uuid:{uuid4()}"
    modified = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    images = _assign_images(chapters)
    nav = nav_xhtml(chapters, language=lang, book_title=book_title)
    opf = _opf(
        chapters,
        images,
        title=book_title,
        language=lang,
        author=author,
        identifier=pub_id,
        modified=modified,
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w") as archive:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        archive.writestr(info, "application/epub+zip")
        _add(archive, "META-INF/container.xml", _CONTAINER)
        _add(archive, "OEBPS/content.opf", opf)
        _add(archive, "OEBPS/nav.xhtml", nav)
        _add(archive, "OEBPS/style.css", STYLESHEET)
        for chapter in chapters:
            _add(
                archive,
                f"OEBPS/{chapter.filename}",
                chapter_xhtml(chapter, language=lang),
            )
        for name, blob in images:
            archive.writestr(f"OEBPS/{name}", blob)


def _assign_images(chapters: list[Chapter]) -> list[tuple[str, bytes]]:
    found: list[tuple[str, bytes]] = []
    number = 0
    for chapter in chapters:
        for block in chapter.blocks:
            if block.kind == "figure" and block.image:
                number += 1
                href = image_name(number, block.image_ext)
                block.image_href = href
                found.append((href, block.image))
    return found


def _add(archive: zipfile.ZipFile, name: str, text: str) -> None:
    archive.writestr(name, text.encode("utf-8"))


def _opf(
    chapters: list[Chapter],
    images: list[tuple[str, bytes]],
    *,
    title: str,
    language: str,
    author: str | None,
    identifier: str,
    modified: str,
) -> str:
    creator = f"<dc:creator>{escape(author)}</dc:creator>\n" if author else ""
    items = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="style" href="style.css" media-type="text/css"/>',
    ]
    spine = []
    for index, chapter in enumerate(chapters, start=1):
        item_id = f"c{index}"
        items.append(
            f'<item id="{item_id}" href="{chapter.filename}" media-type="application/xhtml+xml"/>'
        )
        spine.append(f'<itemref idref="{item_id}"/>')
    for index, (name, blob) in enumerate(images, start=1):
        media = "image/png" if name.endswith(".png") else "image/jpeg"
        items.append(f'<item id="img{index}" href="{name}" media-type="{media}"/>')
        del blob
    manifest = "\n".join(items)
    spine_xml = "\n".join(spine)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<package xmlns="{_OPF_NS}" unique-identifier="pub-id" version="3.0" xml:lang="{escape(language)}">\n'
        f'<metadata xmlns:dc="{_DC_NS}">\n'
        f'<dc:identifier id="pub-id">{escape(identifier)}</dc:identifier>\n'
        f"<dc:title>{escape(title)}</dc:title>\n"
        f"<dc:language>{escape(language)}</dc:language>\n"
        f"{creator}"
        f'<meta property="dcterms:modified">{modified}</meta>\n'
        "</metadata>\n"
        f"<manifest>\n{manifest}\n</manifest>\n"
        f"<spine>\n{spine_xml}\n</spine>\n"
        "</package>\n"
    )


_CONTAINER = """\
<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""
