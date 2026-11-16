from pdf2epub.blocks import Line
from pdf2epub.furniture import drop_furniture, join_hyphens, reading_order
from pdf2epub.markup import lines_to_blocks


def _line(page, x, y, text, size=12, width=600, height=800):
    return Line(page, x, y, size, text, width, height)


def test_repeated_header_and_page_number_are_dropped():
    lines = []
    for page in range(4):
        lines.append(_line(page, 72, 780, "Running Header"))
        lines.append(_line(page, 72, 700, f"Body paragraph on page {page}."))
        lines.append(_line(page, 300, 40, str(page + 1)))
    kept = drop_furniture(lines)
    texts = [line.text for line in kept]
    assert texts == [f"Body paragraph on page {page}." for page in range(4)]


def test_body_text_near_the_middle_is_kept():
    lines = [_line(0, 72, 400, "1"), _line(1, 72, 400, "1")]
    assert [line.text for line in drop_furniture(lines)] == ["1", "1"]


def test_hyphen_at_end_of_line_joins_a_lowercase_continuation():
    lines = [
        _line(0, 72, 700, "The conver-"),
        _line(0, 72, 680, "sion keeps the word."),
    ]
    joined = join_hyphens(lines)
    assert [line.text for line in joined] == ["The conversion keeps the word."]


def test_typewriter_lines_stay_on_their_own_lines():
    lines = [
        _line(0, 72, 400, "F000 >RAM ! ( EFFF, last byte, plus one)", size=10),
        _line(0, 72, 388, ": THERE ( -- address of next free byte in RAM)", size=10),
        _line(0, 72, 376, ">RAM @ ;", size=10),
    ]
    for line in lines:
        line.code = True
    blocks = lines_to_blocks(lines, headings=False)
    assert len(blocks) == 1
    assert blocks[0].kind == "pre"
    assert blocks[0].text.splitlines() == [line.text for line in lines]


def test_a_larger_short_line_becomes_a_heading():
    lines = [
        _line(0, 72, 720, "Chapter One", size=18),
        _line(0, 72, 680, "A short born-digital page.", size=12),
    ]
    blocks = lines_to_blocks(lines, headings=True)
    assert [(block.kind, block.level, block.text) for block in blocks] == [
        ("heading", 1, "Chapter One"),
        ("paragraph", 1, "A short born-digital page."),
    ]


def test_two_columns_are_read_left_then_right():
    lines = [
        _line(0, 40, 700, "Left top"),
        _line(0, 360, 700, "Right top"),
        _line(0, 40, 680, "Left bottom"),
        _line(0, 360, 680, "Right bottom"),
    ]
    ordered = [line.text for line in reading_order(lines)]
    assert ordered == ["Left top", "Left bottom", "Right top", "Right bottom"]
