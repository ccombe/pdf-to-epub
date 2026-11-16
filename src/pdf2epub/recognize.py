"""Recognizer adapters. The EPUB writer never imports Docling or PaddleOCR."""

from pathlib import Path
from typing import Any, Protocol

from pdf2epub.blocks import Block

# PaddleOCR's small document stack. Sizes are the official inference-model
# storage sizes: PP-DocLayout-S 4.8 MB, PP-OCRv5_mobile_det 4.7 MB,
# en_PP-OCRv4_mobile_rec 7.5 MB, PP-OCRv5_mobile_rec 16 MB.
LAYOUT_MODEL = "PP-DocLayout-S"
DET_MODEL = "PP-OCRv5_mobile_det"
REC_MODELS = {
    "en": "en_PP-OCRv4_mobile_rec",
    "zh": "PP-OCRv5_mobile_rec",
}

_SKIP = {"page_header", "page_footer", "furniture"}
_HEADINGS = {"title": 1, "section_header": 2}


class RecognizerUnavailable(RuntimeError):
    pass


class Recognizer(Protocol):
    def recognize(self, pdf_path: Path, page_numbers: list[int]) -> list[Block]: ...

    def recognize_image(self, image_path: Path, page_number: int) -> list[Block]: ...


class DoclingRecognizer:
    """Run Docling on the pages that have no usable text layer.

    CPU is the default. ``gpu=True`` selects CUDA when that build of Docling
    can see a device. Pages are converted in chunks so a long book does not
    have to be one job.
    """

    def __init__(self, *, gpu: bool = False, chunk_pages: int = 20):
        self.gpu = gpu
        self.chunk_pages = max(1, chunk_pages)

    def recognize(self, pdf_path: Path, page_numbers: list[int]) -> list[Block]:
        if not page_numbers:
            return []
        try:
            from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption
        except ImportError as exc:
            raise RecognizerUnavailable(
                "this PDF needs Docling. Install it with: uv sync --extra docling"
            ) from exc

        device = AcceleratorDevice.CUDA if self.gpu else AcceleratorDevice.CPU
        options = PdfPipelineOptions()
        options.accelerator_options = AcceleratorOptions(device=device)
        options.do_ocr = True
        options.do_table_structure = True
        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
        )
        blocks: list[Block] = []
        wanted = set(page_numbers)
        for start, end in _chunks(sorted(wanted), self.chunk_pages):
            result = converter.convert(str(pdf_path), page_range=(start, end))
            blocks.extend(_blocks_from_document(result.document, wanted))
        return blocks

    def recognize_image(self, image_path: Path, page_number: int) -> list[Block]:
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as exc:
            raise RecognizerUnavailable(
                "this PDF needs Docling. Install it with: uv sync --extra docling"
            ) from exc
        result = DocumentConverter().convert(str(image_path))
        blocks = _blocks_from_document(result.document, wanted=None)
        for block in blocks:
            block.page = page_number
        return blocks


def _chunks(pages: list[int], size: int) -> list[tuple[int, int]]:
    if not pages:
        return []
    ranges: list[tuple[int, int]] = []
    start = previous = pages[0]
    for page in pages[1:]:
        if page == previous + 1 and page - start + 1 <= size:
            previous = page
            continue
        ranges.append((start, previous))
        start = previous = page
    ranges.append((start, previous))
    return ranges


def _blocks_from_document(document: Any, wanted: set[int] | None) -> list[Block]:
    blocks: list[Block] = []
    iterator = getattr(document, "iterate_items", None)
    if iterator is None:
        markdown = document.export_to_markdown()
        if markdown.strip():
            blocks.append(Block("paragraph", text=markdown.strip(), source="ocr"))
        return blocks
    for item, _level in iterator():
        layer = str(getattr(item, "content_layer", "body")).lower()
        if "furniture" in layer:
            continue
        label = str(getattr(item, "label", "")).split(".")[-1].lower()
        if label in _SKIP:
            continue
        page = _page_number(item)
        if wanted is not None and page is not None and page not in wanted:
            continue
        page = page or 0
        if label in {"picture", "figure"}:
            image = _picture_bytes(item, document)
            if image is None:
                continue
            blob, ext = image
            blocks.append(
                Block(
                    "figure",
                    page=page - 1 if page else 0,
                    source="ocr",
                    image=blob,
                    image_ext=ext,
                    alt="Figure",
                )
            )
            continue
        text = str(getattr(item, "text", "") or "").strip()
        if label == "table" and not text:
            exporter = getattr(item, "export_to_markdown", None)
            text = exporter(document).strip() if exporter else ""
        if not text:
            continue
        if label in _HEADINGS or label == "section_header":
            level = int(getattr(item, "level", 0) or _HEADINGS.get(label, 2))
            blocks.append(
                Block(
                    "heading",
                    text=text,
                    level=min(max(level, 1), 6),
                    page=max(page - 1, 0),
                    source="ocr",
                )
            )
        elif label == "list_item":
            blocks.append(Block("list_item", text=text, page=max(page - 1, 0), source="ocr"))
        elif (
            label == "caption" and blocks and blocks[-1].kind == "figure" and not blocks[-1].caption
        ):
            blocks[-1].caption = text
            blocks[-1].alt = text
        elif label == "footnote":
            blocks.append(Block("paragraph", text=text, page=max(page - 1, 0), source="footnote"))
        else:
            blocks.append(Block("paragraph", text=text, page=max(page - 1, 0), source="ocr"))
    return blocks


def _page_number(item: Any) -> int | None:
    prov = getattr(item, "prov", None) or []
    if not prov:
        return None
    number = getattr(prov[0], "page_no", None)
    return int(number) if number else None


def _picture_bytes(item: Any, document: Any) -> tuple[bytes, str] | None:
    getter = getattr(item, "get_image", None)
    if getter is None:
        return None
    try:
        pil = getter(document)
    except Exception:
        return None
    if pil is None:
        return None
    from io import BytesIO

    buffer = BytesIO()
    if getattr(pil, "mode", "") == "RGBA":
        pil.save(buffer, format="PNG")
        return buffer.getvalue(), "png"
    pil.convert("RGB").save(buffer, format="JPEG", quality=85)
    return buffer.getvalue(), "jpeg"


_PADDLE_SKIP = {"header", "footer", "page_number", "number", "seal", "header_image", "footer_image"}
_PADDLE_H1 = {"doc_title", "document_title", "title"}
_PADDLE_H2 = {"paragraph_title"}
_PADDLE_FIGURE = {"image", "chart", "figure"}
_PADDLE_CAPTION = {"figure_title", "figure_caption", "chart_title", "table_title", "image_title"}


class PaddleRecognizer:
    """PP-DocLayout-S plus the PP-OCR mobile detection and recognition models.

    Those are the small PaddleOCR models. CPU is the default. ``gpu=True``
    passes ``device="gpu"``. Formula and table models stay off so a book does
    not download the large ones.
    """

    def __init__(self, *, gpu: bool = False, language: str = "en"):
        self.gpu = gpu
        self.language = language
        self._pipeline = None

    def recognize(self, pdf_path: Path, page_numbers: list[int]) -> list[Block]:
        if not page_numbers:
            return []
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(pdf_path))
        blocks: list[Block] = []
        try:
            for number in page_numbers:
                image = pdf[number - 1].render(scale=150 / 72).to_pil()
                blocks.extend(self._predict(image, number - 1))
        finally:
            pdf.close()
        return blocks

    def recognize_image(self, image_path: Path, page_number: int) -> list[Block]:
        from PIL import Image

        with Image.open(image_path) as image:
            return self._predict(image.convert("RGB"), page_number - 1)

    def _predict(self, image: Any, page_index: int) -> list[Block]:
        import numpy as np

        raw = self._load().predict(np.array(image.convert("RGB")))
        pages = list(raw) if raw is not None else []
        blocks: list[Block] = []
        for page in pages:
            blocks.extend(blocks_from_paddle(page, page_index, image))
        return blocks

    def _load(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline
        try:
            from paddleocr import PPStructureV3
        except ImportError as exc:
            raise RecognizerUnavailable(
                "this PDF needs the PaddleOCR mobile models. Install them with: uv sync --extra ocr"
            ) from exc
        lang = "zh" if self.language.lower().startswith("zh") else "en"
        self._pipeline = PPStructureV3(
            device="gpu" if self.gpu else "cpu",
            layout_detection_model_name=LAYOUT_MODEL,
            text_detection_model_name=DET_MODEL,
            text_recognition_model_name=REC_MODELS[lang],
            use_table_recognition=False,
            use_formula_recognition=False,
            use_seal_recognition=False,
        )
        return self._pipeline


def blocks_from_paddle(page: Any, page_index: int, image: Any = None) -> list[Block]:
    """Map one PP-StructureV3 page result into blocks."""
    payload = page
    if hasattr(page, "json"):
        try:
            payload = page.json
        except Exception:
            payload = page
    if isinstance(payload, dict) and "res" in payload and isinstance(payload["res"], dict):
        payload = payload["res"]
    regions = []
    if isinstance(payload, dict):
        regions = payload.get("parsing_res_list") or []
    blocks: list[Block] = []
    for region in regions:
        if not isinstance(region, dict):
            region = {
                "block_label": getattr(region, "block_label", ""),
                "block_content": getattr(region, "block_content", ""),
                "block_bbox": getattr(region, "block_bbox", None),
            }
        label = (
            str(region.get("block_label") or "").strip().lower().replace(" ", "_").replace("-", "_")
        )
        text = str(region.get("block_content") or "").strip()
        if label in _PADDLE_SKIP:
            continue
        if (
            label in _PADDLE_CAPTION
            and blocks
            and blocks[-1].kind == "figure"
            and not blocks[-1].caption
        ):
            blocks[-1].caption = text
            blocks[-1].alt = text or blocks[-1].alt
            continue
        if label in _PADDLE_FIGURE:
            blob = _crop(image, region.get("block_bbox"))
            if blob is None:
                if text:
                    blocks.append(Block("paragraph", text=text, page=page_index, source="ocr"))
                continue
            blocks.append(
                Block(
                    "figure",
                    page=page_index,
                    source="ocr",
                    image=blob[0],
                    image_ext=blob[1],
                    alt=text or "Figure",
                )
            )
            continue
        if not text:
            continue
        if label in _PADDLE_H1:
            blocks.append(Block("heading", text=text, level=1, page=page_index, source="ocr"))
        elif label in _PADDLE_H2:
            blocks.append(Block("heading", text=text, level=2, page=page_index, source="ocr"))
        elif label == "footnote":
            blocks.append(Block("paragraph", text=text, page=page_index, source="footnote"))
        else:
            blocks.append(Block("paragraph", text=text, page=page_index, source="ocr"))
    return blocks


def _crop(image: Any, bbox: Any) -> tuple[bytes, str] | None:
    if image is None or bbox is None:
        return None
    try:
        values = [int(float(value)) for value in list(bbox)[:4]]
    except (TypeError, ValueError):
        return None
    if len(values) < 4:
        return None
    x1, y1, x2, y2 = values
    if x2 - x1 < 32 or y2 - y1 < 32:
        return None
    crop = image.crop((max(x1, 0), max(y1, 0), x2, y2))
    from io import BytesIO

    buffer = BytesIO()
    crop.convert("RGB").save(buffer, format="JPEG", quality=85)
    return buffer.getvalue(), "jpeg"
