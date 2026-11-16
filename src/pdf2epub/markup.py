"""Turn blocks into the closed XHTML subset, and group pages into chapters."""

import re
from xml.sax.saxutils import escape

from pdf2epub.blocks import Block, Chapter, Line, OutlineEntry

_LIST_ITEM = re.compile(r"^(?:\d+[\.\)]|[•·])\s+\S")
_CONTENTS_ENTRY = re.compile(r".{3,}(?:,\s*)?(?:\d{1,4}|[ivxlcdm]{1,8})\s*$", re.IGNORECASE)
_XML_TEXT = escape


def lines_to_blocks(lines: list[Line], *, headings: bool) -> list[Block]:
    if not headings:
        return _paragraphs_and_lists(lines, heading_size=None)
    sizes = sorted(line.size for line in lines if line.text.strip())
    if not sizes:
        return []
    body = sizes[(len(sizes) - 1) // 2] or 12
    return _paragraphs_and_lists(lines, heading_size=body * 1.2)


def _paragraphs_and_lists(lines: list[Line], heading_size: float | None) -> list[Block]:
    blocks: list[Block] = []
    paragraph: list[str] = []
    paragraph_page = 0
    paragraph_y = 0.0
    list_items: list[tuple[int, str]] = []
    code_lines: list[Line] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        text = _normalize(" ".join(paragraph))
        if text:
            blocks.append(
                Block("paragraph", text=text, page=paragraph_page, source="text", y=paragraph_y)
            )
        paragraph = []

    def flush_code() -> None:
        nonlocal code_lines
        if code_lines:
            blocks.append(
                Block(
                    "pre",
                    text="\n".join(line.text for line in code_lines),
                    page=code_lines[0].page,
                    source="code",
                    y=code_lines[0].y,
                )
            )
        code_lines = []

    def flush_list() -> None:
        nonlocal list_items
        for page, text in list_items:
            blocks.append(Block("list_item", text=text, page=page, source="text", y=paragraph_y))
        list_items = []

    previous: Line | None = None
    for line in lines:
        text = _normalize(line.text)
        if not text:
            continue
        if line.code:
            flush_list()
            flush_paragraph()
            code_lines.append(line)
            previous = line
            continue
        if code_lines:
            flush_code()
        if heading_size is not None and line.size >= heading_size and len(text) <= 80:
            flush_list()
            flush_paragraph()
            level = 1 if line.size >= heading_size * 1.15 else 2
            blocks.append(
                Block("heading", text=text, level=level, page=line.page, source="font", y=line.y)
            )
            previous = line
            continue
        item = _LIST_ITEM.match(text)
        if item:
            flush_paragraph()
            list_items.append((line.page, _strip_marker(text)))
            previous = line
            continue
        if list_items:
            flush_list()
        gap = 0.0 if previous is None or previous.page != line.page else previous.y - line.y
        typical = max(line.size, 10) * 1.6
        if paragraph and (_CONTENTS_ENTRY.match(paragraph[-1]) or gap > typical):
            flush_paragraph()
        if not paragraph:
            paragraph_page = line.page
            paragraph_y = line.y
        paragraph.append(text)
        previous = line
    flush_code()
    flush_list()
    flush_paragraph()
    return blocks


def _strip_marker(text: str) -> str:
    return re.sub(r"^(?:\d+[\.\)]|[•·])\s+", "", text).strip()


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def chapterize(
    blocks: list[Block],
    outline: list[OutlineEntry],
    *,
    fallback_title: str,
) -> list[Chapter]:
    """One spine document per level-1 outline entry. Without an outline, one document."""
    if not any(entry.level == 1 for entry in outline):
        heading = next(
            (
                block.text
                for block in blocks
                if block.kind == "heading" and block.level == 1 and block.text
            ),
            None,
        )
        title = heading or fallback_title or "Book"
        return [Chapter(title=title, filename="chapter-01.xhtml", blocks=list(blocks))]

    inserted = _with_outline_headings(blocks, outline)
    chapters: list[Chapter] = []
    current: list[Block] = []
    current_title = fallback_title or "Front matter"
    for block in inserted:
        if block.kind == "heading" and block.level == 1 and block.source == "outline" and current:
            chapters.append(_chapter(len(chapters) + 1, current_title, current))
            current = []
            current_title = block.text or current_title
        if block.kind == "heading" and block.level == 1 and block.source == "outline":
            current_title = block.text or current_title
        current.append(block)
    if current:
        chapters.append(_chapter(len(chapters) + 1, current_title, current))
    if not chapters:
        chapters.append(_chapter(1, fallback_title or "Book", []))
    return chapters


def _with_outline_headings(blocks: list[Block], outline: list[OutlineEntry]) -> list[Block]:
    headings = [
        Block(
            "heading",
            text=_normalize(entry.title),
            level=min(max(entry.level, 1), 6),
            page=entry.page,
            source="outline",
        )
        for entry in outline
        if entry.title.strip()
    ]
    merged: list[Block] = []
    heading_index = 0
    block_index = 0
    while block_index < len(blocks) or heading_index < len(headings):
        next_heading = headings[heading_index] if heading_index < len(headings) else None
        next_block = blocks[block_index] if block_index < len(blocks) else None
        if next_heading is not None and (
            next_block is None or next_heading.page <= next_block.page
        ):
            if not _same_heading(merged, next_heading):
                merged.append(next_heading)
            heading_index += 1
            continue
        if next_block is not None:
            merged.append(next_block)
            block_index += 1
    return merged


def _same_heading(existing: list[Block], heading: Block) -> bool:
    if not existing:
        return False
    last = existing[-1]
    return last.kind == "heading" and last.text.casefold() == heading.text.casefold()


def _chapter(number: int, title: str, blocks: list[Block]) -> Chapter:
    safe = _normalize(title) or f"Chapter {number}"
    return Chapter(title=safe, filename=f"chapter-{number:02d}.xhtml", blocks=blocks)


def chapter_xhtml(chapter: Chapter, *, language: str, stylesheet: str = "style.css") -> str:
    title = _XML_TEXT(chapter.title)
    body = _body(chapter.blocks)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{_XML_TEXT(language)}" lang="{_XML_TEXT(language)}">\n'
        "<head>\n"
        f"<title>{title}</title>\n"
        f'<link rel="stylesheet" type="text/css" href="{stylesheet}"/>\n'
        "</head>\n"
        f"<body>\n{body}</body>\n"
        "</html>\n"
    )


def nav_xhtml(chapters: list[Chapter], *, language: str, book_title: str) -> str:
    items = []
    for chapter in chapters:
        label = _XML_TEXT(chapter.title)
        href = chapter.filename
        nested = _nested_nav(chapter)
        items.append(f'<li><a href="{href}">{label}</a>{nested}</li>')
    listing = "\n".join(items) if items else '<li><a href="chapter-01.xhtml">Book</a></li>'
    title = _XML_TEXT(book_title)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" '
        f'xml:lang="{_XML_TEXT(language)}" lang="{_XML_TEXT(language)}">\n'
        "<head>\n"
        f"<title>{title}</title>\n"
        '<link rel="stylesheet" type="text/css" href="style.css"/>\n'
        "</head>\n"
        "<body>\n"
        '<nav epub:type="toc" id="toc">\n'
        f"<h1>{title}</h1>\n"
        f"<ol>\n{listing}\n</ol>\n"
        "</nav>\n"
        "</body>\n"
        "</html>\n"
    )


def _nested_nav(chapter: Chapter) -> str:
    children = []
    for index, block in enumerate(chapter.blocks):
        if block.kind == "heading" and block.level >= 2 and block.text:
            anchor = f"h-{index}"
            children.append(
                f'<li><a href="{chapter.filename}#{anchor}">{_XML_TEXT(block.text)}</a></li>'
            )
    if not children:
        return ""
    return "<ol>\n" + "\n".join(children) + "\n</ol>"


def _body(blocks: list[Block]) -> str:
    parts: list[str] = []
    index = 0
    while index < len(blocks):
        block = blocks[index]
        if block.kind == "list_item":
            items = []
            while index < len(blocks) and blocks[index].kind == "list_item":
                items.append(f"<li>{_inline(blocks[index].text)}</li>")
                index += 1
            parts.append("<ul>\n" + "\n".join(items) + "\n</ul>")
            continue
        if block.kind == "pre" and block.text:
            parts.append(f"<pre>{escape(block.text)}</pre>")
        elif block.kind == "heading":
            level = min(max(block.level, 1), 6)
            anchor = f' id="h-{index}"' if level >= 2 else ""
            parts.append(f"<h{level}{anchor}>{_inline(block.text)}</h{level}>")
        elif block.kind == "figure" and block.image:
            parts.append(_figure(block, index))
        elif block.text:
            css = ' class="footnote"' if block.source == "footnote" else ""
            parts.append(f"<p{css}>{_inline(block.text)}</p>")
        index += 1
    return "\n".join(parts) + ("\n" if parts else "")


def _figure(block: Block, index: int) -> str:
    src = block.image_href or f"images/fig-{index:04d}.{block.image_ext}"
    alt = _XML_TEXT(block.alt or block.caption or "Figure")
    caption = f"\n<figcaption>{_inline(block.caption)}</figcaption>" if block.caption else ""
    return f'<figure>\n<img src="{src}" alt="{alt}"/>{caption}\n</figure>'


def _inline(text: str) -> str:
    return _XML_TEXT(_normalize(text))


def image_name(index: int, ext: str) -> str:
    return f"images/fig-{index:04d}.{ext}"


STYLESHEET = """\
body {
  font-family: serif;
  line-height: 1.45;
  margin: 1em;
}
h1, h2, h3, h4, h5, h6 {
  font-family: sans-serif;
  line-height: 1.2;
  margin: 1.2em 0 0.4em;
}
p, ul, ol, figure, pre {
  margin: 0.6em 0;
}
pre {
  font-family: monospace;
  font-size: 0.85em;
  line-height: 1.35;
  white-space: pre-wrap;
}
img {
  max-width: 100%;
  height: auto;
}
figcaption, p.footnote {
  font-size: 0.9em;
}
"""
