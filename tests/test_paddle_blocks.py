from PIL import Image

from pdf2epub.recognize import blocks_from_paddle


def test_paddle_regions_become_headings_prose_and_a_cropped_figure():
    image = Image.new("RGB", (200, 200), "white")
    page = {
        "parsing_res_list": [
            {
                "block_label": "doc_title",
                "block_content": "Chapter One",
                "block_bbox": [0, 0, 10, 10],
            },
            {
                "block_label": "text",
                "block_content": "Hello from the scan.",
                "block_bbox": [0, 20, 10, 40],
            },
            {
                "block_label": "header",
                "block_content": "Running Header",
                "block_bbox": [0, 0, 10, 10],
            },
            {"block_label": "image", "block_content": "", "block_bbox": [10, 10, 80, 90]},
            {
                "block_label": "figure_title",
                "block_content": "A plate",
                "block_bbox": [10, 90, 80, 110],
            },
        ]
    }
    blocks = blocks_from_paddle(page, 2, image)
    assert [(block.kind, block.text or block.caption, block.level) for block in blocks] == [
        ("heading", "Chapter One", 1),
        ("paragraph", "Hello from the scan.", 1),
        ("figure", "A plate", 1),
    ]
    assert blocks[2].image
    assert blocks[2].page == 2
