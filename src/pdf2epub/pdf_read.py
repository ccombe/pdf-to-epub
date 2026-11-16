"""Read a Source PDF: metadata, outline, text lines, and figures."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from pdf2epub.blocks import Block, Line, OutlineEntry

_MIN_FIGURE_PX = 32
_FULL_PAGE = 0.75
_TEXT_TRUST = 40


class PasswordRequired(Exception):
    def __init__(self, name: str):
        super().__init__(f"password required for {name}")


class BadPassword(Exception):
    def __init__(self, name: str):
        super().__init__(f"bad password for {name}")


@dataclass
class PageInfo:
    number: int
    width: float
    height: float
    lines: list[Line] = field(default_factory=list)
    figures: list[Block] = field(default_factory=list)
    full_page_image: bool = False
    page_class: str = "born-digital"


@dataclass
class PdfDocument:
    path: Path
    title: str | None
    author: str | None
    tagged: bool
    pages: list[PageInfo]
    outline: list[OutlineEntry]


def read_pdf(path: Path, password: str | None) -> PdfDocument:
    try:
        reader = PdfReader(str(path))
    except PdfReadError as exc:
        raise PdfReadError(f"cannot read {path.name}: {exc}") from exc
    if reader.is_encrypted:
        if not password:
            raise PasswordRequired(path.name)
        status = reader.decrypt(password)
        if status == 0:
            raise BadPassword(path.name)
    try:
        pdf = pdfium.PdfDocument(str(path), password=password)
    except pdfium.PdfiumError as exc:
        message = str(exc).lower()
        if "password" in message:
            if not password:
                raise PasswordRequired(path.name) from exc
            raise BadPassword(path.name) from exc
        raise
    meta = reader.metadata
    title = _clean(getattr(meta, "title", None)) if meta else None
    author = _clean(getattr(meta, "author", None)) if meta else None
    tagged = _is_tagged(reader)
    pages = [_read_page(reader, pdf, index) for index in range(len(reader.pages))]
    outline = _outline(reader)
    pdf.close()
    return PdfDocument(path, title, author, tagged, pages, outline)


def _clean(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _is_tagged(reader: PdfReader) -> bool:
    try:
        root = reader.trailer.get("/Root")
        if root is None:
            return False
        resolved = root.get_object()
        return "/StructTreeRoot" in resolved
    except Exception:
        return False


def _read_page(reader: PdfReader, pdf: pdfium.PdfDocument, index: int) -> PageInfo:
    page = reader.pages[index]
    box = page.mediabox
    width = float(box.width)
    height = float(box.height)
    raw = pdf[index]
    raw_width = float(raw.get_width()) or width
    raw_height = float(raw.get_height()) or height
    fragments = _fragments(page)
    if not fragments:
        fragments = _fragments_from_pdfium(raw, raw_width, raw_height)
    lines = _group_lines(fragments, index, raw_width, raw_height)
    figures, full_page = _figures(raw, index, raw_width, raw_height)
    lines = [line for line in lines if not _inside_figure(line, figures)]
    info = PageInfo(index, raw_width, raw_height, lines, figures, full_page)
    info.page_class = _classify(info)
    return info


def _fragments(page) -> list[tuple[float, float, float, str, bool]]:
    found: list[tuple[float, float, float, str, bool]] = []

    def visitor(text, _cm, tm, font, font_size):
        if text and text.strip():
            name = ""
            if font:
                name = str(font.get("/BaseFont", ""))
            found.append(
                (float(tm[4]), float(tm[5]), float(font_size or 12), text, _code_font(name))
            )

    page.extract_text(visitor_text=visitor)
    return found


def _code_font(name: str) -> bool:
    base = name.split("+")[-1].lower()
    return any(
        token in base for token in ("sftt", "cmtt", "courier", "mono", "typewriter", "consol")
    )


def _fragments_from_pdfium(
    raw: Any, width: float, height: float
) -> list[tuple[float, float, float, str, bool]]:
    textpage = raw.get_textpage()
    text = (textpage.get_text_bounded() or "").replace("\r\n", "\n").replace("\r", "\n")
    textpage.close()
    lines = [line for line in text.split("\n") if line.strip()]
    if not lines:
        return []
    step = height / (len(lines) + 1)
    return [
        (72.0, height - step * (offset + 1), 12.0, line, False) for offset, line in enumerate(lines)
    ]


def _group_lines(fragments, page: int, width: float, height: float) -> list[Line]:
    if not fragments:
        return []
    ordered = sorted(fragments, key=lambda item: (-item[1], item[0]))
    groups: list[list[tuple[float, float, float, str, bool]]] = [[ordered[0]]]
    for item in ordered[1:]:
        anchor = groups[-1][0]
        tolerance = max(2.0, anchor[2] * 0.45)
        if abs(item[1] - anchor[1]) <= tolerance:
            groups[-1].append(item)
        else:
            groups.append([item])
    lines: list[Line] = []
    for group in groups:
        group.sort(key=lambda item: item[0])
        pieces = [group[0][3]]
        cursor = group[0][0] + max(len(group[0][3]), 1) * group[0][2] * 0.45
        size = group[0][2]
        for item in group[1:]:
            if item[0] > cursor + size * 0.15:
                pieces.append(" ")
            pieces.append(item[3])
            cursor = item[0] + max(len(item[3]), 1) * item[2] * 0.45
            size = max(size, item[2])
        text = "".join(pieces).strip()
        if text:
            code_chars = sum(len(item[3]) for item in group if item[4])
            plain_chars = sum(len(item[3]) for item in group if not item[4])
            lines.append(
                Line(
                    page,
                    group[0][0],
                    group[0][1],
                    size,
                    text,
                    width,
                    height,
                    code=code_chars > plain_chars and code_chars >= 8,
                )
            )
    return lines


def _figures(raw, page: int, width: float, height: float) -> tuple[list[Block], bool]:
    figures: list[Block] = []
    full_page = False
    page_area = max(width * height, 1)
    try:
        objects = list(raw.get_objects(max_depth=2))
    except Exception:
        return [], False
    path_boxes: list[list[float]] = []
    text_boxes: list[list[float]] = []
    for obj in objects:
        try:
            kind = int(obj.type)
            left, bottom, right, top = obj.get_bounds()
        except Exception:
            continue
        box_w = max(right - left, 0)
        box_h = max(top - bottom, 0)
        if kind == int(pdfium.raw.FPDF_PAGEOBJ_TEXT) and 4 <= box_w <= 180 and 3 <= box_h <= 22:
            text_boxes.append([left, bottom, right, top])
        if kind == int(pdfium.raw.FPDF_PAGEOBJ_IMAGE):
            if box_w * box_h >= page_area * _FULL_PAGE:
                full_page = True
                continue
            image = _render_object(obj)
            if image is None:
                continue
            blob, _ext = image
            figures.append(
                Block(
                    "figure",
                    page=page,
                    source="image",
                    image=blob,
                    image_ext="png",
                    alt="Figure",
                    y=top,
                    left=left,
                    bottom=bottom,
                    right=right,
                )
            )
            continue
        if kind == int(pdfium.raw.FPDF_PAGEOBJ_PATH) and _is_diagram_stroke(box_w, box_h, width):
            path_boxes.append([left, bottom, right, top])
    for box in _cluster_boxes(path_boxes, gap=10):
        # One pass against the stroke box. Labels sit just outside the lines;
        # growing from each new word would walk down the paragraph.
        covered = _cover_labels(box, text_boxes)
        region = [
            max(covered[0] - 4, 0),
            max(covered[1] - 4, 0),
            min(covered[2] + 4, width),
            min(covered[3] + 4, height),
        ]
        region_w = region[2] - region[0]
        region_h = region[3] - region[1]
        if region_w < 36 or region_h < 36:
            continue
        if region_w * region_h > page_area * 0.72:
            continue
        if region_w > width * 0.92 and region_h > height * 0.85:
            continue
        png = _render_region(raw, region)
        if png is None:
            continue
        figures.append(
            Block(
                "figure",
                page=page,
                source="diagram",
                image=png,
                image_ext="png",
                alt="Figure",
                y=region[3],
                left=region[0],
                bottom=region[1],
                right=region[2],
            )
        )
    return figures, full_page


def _is_diagram_stroke(width: float, height: float, page_width: float) -> bool:
    short = min(width, height)
    long = max(width, height)
    if long < 4 or short < 0.35:
        return False
    # A hairline that spans the text column is a rule, not a diagram edge.
    return not (short < 2.5 and long > page_width * 0.62)


def _cover_labels(box: list[float], labels: list[list[float]]) -> list[float]:
    left, bottom, right, top = box
    for label_left, label_bottom, label_right, label_top in labels:
        center_x = (label_left + label_right) / 2
        if center_x < box[0] - 8 or center_x > box[2] + 8:
            continue
        if label_bottom > box[3] + 32 or label_top < box[1] - 8:
            continue
        left = min(left, label_left)
        bottom = min(bottom, label_bottom)
        right = max(right, label_right)
        top = max(top, label_top)
    return [left, bottom, right, top]


def _cluster_boxes(boxes: list[list[float]], gap: float) -> list[list[float]]:
    clusters: list[list[float]] = []
    for box in boxes:
        merged = False
        for cluster in clusters:
            if _near(cluster, box, gap):
                _union(cluster, box)
                merged = True
                break
        if not merged:
            clusters.append(list(box))
    changed = True
    while changed:
        changed = False
        index = 0
        while index < len(clusters):
            other = index + 1
            while other < len(clusters):
                if _near(clusters[index], clusters[other], gap):
                    _union(clusters[index], clusters[other])
                    del clusters[other]
                    changed = True
                else:
                    other += 1
            index += 1
    return clusters


def _near(one: list[float], other: list[float], gap: float) -> bool:
    return not (
        one[2] + gap < other[0]
        or other[2] + gap < one[0]
        or one[3] + gap < other[1]
        or other[3] + gap < one[1]
    )


def _union(target: list[float], box: list[float]) -> None:
    target[0] = min(target[0], box[0])
    target[1] = min(target[1], box[1])
    target[2] = max(target[2], box[2])
    target[3] = max(target[3], box[3])


def _inside_figure(line: Line, figures: list[Block]) -> bool:
    # Captions stay as text. Diagram words, including typewriter labels, are in the picture.
    if line.text.lower().startswith("figure"):
        return False
    for figure in figures:
        if figure.source != "diagram" or not figure.image:
            continue
        if (
            figure.left - 2 <= line.x <= figure.right + 2
            and figure.bottom - 4 <= line.y <= figure.y + 2
        ):
            return True
    return False


def _render_region(raw, region: list[float]) -> bytes | None:
    scale = 2.0
    try:
        pil = raw.render(scale=scale).to_pil()
    except Exception:
        return None
    height = float(raw.get_height())
    left = max(int(region[0] * scale), 0)
    top = max(int((height - region[3]) * scale), 0)
    right = min(int(region[2] * scale), pil.width)
    bottom = min(int((height - region[1]) * scale), pil.height)
    if right - left < 40 or bottom - top < 40:
        return None
    from io import BytesIO

    buffer = BytesIO()
    pil.crop((left, top, right, bottom)).save(buffer, format="PNG")
    return buffer.getvalue()


def _render_object(obj) -> tuple[bytes, str] | None:
    try:
        bitmap = obj.get_bitmap(render=True)
        pil = bitmap.to_pil()
    except Exception:
        return None
    if pil.width < _MIN_FIGURE_PX or pil.height < _MIN_FIGURE_PX:
        return None
    from io import BytesIO

    buffer = BytesIO()
    if pil.mode not in ("RGB", "RGBA"):
        pil = pil.convert("RGBA")
    pil.save(buffer, format="PNG")
    return buffer.getvalue(), "png"


def _classify(page: PageInfo) -> str:
    letters = sum(1 for ch in " ".join(line.text for line in page.lines) if ch.isalnum())
    wide = page.width >= page.height * 1.25
    if page.full_page_image and wide:
        return "spread"
    if page.full_page_image and letters < _TEXT_TRUST:
        return "scan"
    if page.full_page_image:
        return "ocr-layer"
    return "born-digital"


def _outline(reader: PdfReader) -> list[OutlineEntry]:
    try:
        items = reader.outline
    except Exception:
        return []
    if not items:
        return []
    found: list[OutlineEntry] = []

    def walk(nodes, level: int) -> None:
        for node in nodes:
            if isinstance(node, list):
                walk(node, level + 1)
                continue
            title = str(getattr(node, "title", "") or "").strip()
            try:
                page = reader.get_destination_page_number(node)
            except Exception:
                page = None
            if title and page is not None and page >= 0:
                found.append(OutlineEntry(title, int(page), level))

    walk(items, 1)
    return found


def alphanumeric_count(page: PageInfo) -> int:
    return sum(1 for ch in " ".join(line.text for line in page.lines) if ch.isalnum())
