"""Drop running headers, footers, and page numbers, then join end-of-line hyphens."""

import re

from pdf2epub.blocks import Line

_PAGE_NUMBER = re.compile(r"(?:page\s+)?(?:\d+|[ivxlcdm]+)\.?", re.IGNORECASE)
_HYPHEN_END = re.compile(r"[A-Za-z]-$")


def _key(text: str) -> str:
    folded = re.sub(r"\d+", "#", text.lower())
    return re.sub(r"\s+", " ", folded).strip()


def _in_zone(line: Line) -> bool:
    if line.page_height <= 0:
        return False
    ratio = line.y / line.page_height
    return ratio >= 0.90 or ratio <= 0.08


def _is_page_number(text: str) -> bool:
    return _PAGE_NUMBER.fullmatch(text.strip()) is not None


def drop_furniture(lines: list[Line]) -> list[Line]:
    """Remove repeated running furniture and bare page numbers in the margins.

    A short line in the top or bottom band is furniture when the same text,
    with digits folded away, shows up on at least two pages and on at least
    40% of the pages. A line that is only a page number is dropped from those
    bands whenever the book has more than one page. Body lines are kept.
    """
    if not lines:
        return []
    pages = {line.page for line in lines}
    page_count = max(len(pages), 1)
    counts: dict[str, set[int]] = {}
    for line in lines:
        if not _in_zone(line) or len(line.text) > 80:
            continue
        key = _key(line.text)
        if len(key) < 2:
            continue
        counts.setdefault(key, set()).add(line.page)
    repeated = {
        key
        for key, seen in counts.items()
        if len(seen) >= 2 and len(seen) >= max(2, int(page_count * 0.4 + 0.999))
    }
    kept: list[Line] = []
    for line in lines:
        if _in_zone(line) and len(line.text) <= 80:
            if page_count > 1 and _is_page_number(line.text):
                continue
            if _key(line.text) in repeated:
                continue
        kept.append(line)
    return kept


def reading_order(lines: list[Line]) -> list[Line]:
    """Top to bottom. When a page has two text columns, read the left one first."""
    by_page: dict[int, list[Line]] = {}
    for line in lines:
        by_page.setdefault(line.page, []).append(line)
    ordered: list[Line] = []
    for page in sorted(by_page):
        group = by_page[page]
        width = group[0].page_width or 1
        left = [line for line in group if line.x < width * 0.48]
        right = [line for line in group if line.x >= width * 0.52]
        middle = [line for line in group if width * 0.48 <= line.x < width * 0.52]
        if _two_columns(left, right):
            ordered.extend(_by_baseline(left))
            ordered.extend(_by_baseline(middle))
            ordered.extend(_by_baseline(right))
        else:
            ordered.extend(_by_baseline(group))
    return ordered


def _two_columns(left: list[Line], right: list[Line]) -> bool:
    """Separate columns. A contents line with a page number on the same row is not one."""
    if len(left) < 2 or len(right) < 2:
        return False
    right_by_row: dict[int, list[Line]] = {}
    for line in right:
        right_by_row.setdefault(round(line.y), []).append(line)
    leaders = 0
    for line in left:
        mates = right_by_row.get(round(line.y), [])
        if mates and all(len(mate.text.strip()) <= 6 for mate in mates):
            leaders += 1
    if leaders >= max(2, int(len(left) * 0.4)):
        return False
    left_y = [line.y for line in left]
    right_y = [line.y for line in right]
    overlap = min(max(left_y), max(right_y)) - max(min(left_y), min(right_y))
    return overlap > 15


def _by_baseline(lines: list[Line]) -> list[Line]:
    return sorted(lines, key=lambda line: (-line.y, line.x))


def join_hyphens(lines: list[Line]) -> list[Line]:
    """Join a word split with a hyphen at the end of a line onto the next line."""
    if not lines:
        return []
    joined: list[Line] = []
    index = 0
    while index < len(lines):
        current = lines[index]
        text = current.text.rstrip()
        while (
            index + 1 < len(lines)
            and not current.code
            and not lines[index + 1].code
            and _HYPHEN_END.search(text)
            and lines[index + 1].text[:1].islower()
        ):
            nxt = lines[index + 1]
            text = text[:-1] + nxt.text.lstrip()
            index += 1
        joined.append(
            Line(
                current.page,
                current.x,
                current.y,
                current.size,
                text,
                current.page_width,
                current.page_height,
                code=current.code,
            )
        )
        index += 1
    return joined
