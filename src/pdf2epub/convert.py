"""Convert one Source PDF into one EPUB, and run a Batch of them."""

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

from pdf2epub.blocks import Block
from pdf2epub.epub import write_epub
from pdf2epub.furniture import drop_furniture, join_hyphens, reading_order
from pdf2epub.markup import chapterize, lines_to_blocks
from pdf2epub.pdf_read import (
    BadPassword,
    PageInfo,
    PasswordRequired,
    PdfDocument,
    alphanumeric_count,
    read_pdf,
)
from pdf2epub.recognize import (
    DoclingRecognizer,
    PaddleRecognizer,
    Recognizer,
    RecognizerUnavailable,
)


@dataclass
class ConvertOptions:
    output_dir: Path
    password: str | None = None
    passwords: dict[str, str] | None = None
    title: str | None = None
    author: str | None = None
    language: str = "en"
    force: bool = False
    recognizer: str = "paddle"
    gpu: bool = False
    chunk_pages: int = 20


@dataclass
class FileResult:
    source: str
    status: str
    epub: str | None = None
    pages: int | None = None
    tagged: bool | None = None
    error: str | None = None

    def as_json(self) -> str:
        payload: dict[str, str | int | bool] = {"source": self.source, "status": self.status}
        if self.epub:
            payload["epub"] = self.epub
        if self.pages is not None:
            payload["pages"] = self.pages
        if self.tagged is not None:
            payload["tagged"] = self.tagged
        if self.error:
            payload["error"] = self.error
        return json.dumps(payload, ensure_ascii=False)


def convert_file(
    path: Path, options: ConvertOptions, recognizer: Recognizer | None = None
) -> FileResult:
    source = str(path)
    if not path.exists():
        return FileResult(source, "error", error="file not found")
    if path.suffix.lower() != ".pdf":
        return FileResult(source, "error", error="not a PDF")
    dest = options.output_dir / f"{path.stem}.epub"
    if dest.exists() and not options.force:
        return FileResult(source, "skipped", epub=str(dest))
    password = _password_for(path, options)
    try:
        document = read_pdf(path, password)
        blocks = _blocks(document, password, options, recognizer)
        chapters = chapterize(
            blocks,
            document.outline,
            fallback_title=options.title or document.title or path.stem,
        )
        write_epub(
            dest,
            chapters,
            title=options.title or document.title or path.stem,
            language=options.language,
            author=options.author if options.author is not None else document.author,
        )
    except (
        PasswordRequired,
        BadPassword,
        RecognizerUnavailable,
        PdfReadError,
        pdfium.PdfiumError,
    ) as exc:
        return FileResult(source, "error", error=str(exc))
    except Exception as exc:
        return FileResult(source, "error", error=str(exc))
    return FileResult(
        source,
        "ok",
        epub=str(dest),
        pages=len(document.pages),
        tagged=document.tagged,
    )


def convert_batch(
    paths: list[Path], options: ConvertOptions, recognizer: Recognizer | None = None
) -> list[FileResult]:
    options.output_dir.mkdir(parents=True, exist_ok=True)
    return [convert_file(path, options, recognizer) for path in paths]


def _password_for(path: Path, options: ConvertOptions) -> str | None:
    if options.passwords and path.name in options.passwords:
        return options.passwords[path.name]
    return options.password


def _blocks(
    document: PdfDocument,
    password: str | None,
    options: ConvertOptions,
    recognizer: Recognizer | None,
) -> list[Block]:
    trusted_lines = []
    figure_blocks: list[Block] = []
    needs_ocr: list[PageInfo] = []
    for page in document.pages:
        if _trust_text(page):
            trusted_lines.extend(page.lines)
            figure_blocks.extend(page.figures)
        else:
            needs_ocr.append(page)
    ordered = join_hyphens(reading_order(drop_furniture(trusted_lines)))
    use_font_headings = not any(entry.level == 1 for entry in document.outline)
    blocks = lines_to_blocks(ordered, headings=use_font_headings)
    blocks.extend(figure_blocks)
    if needs_ocr:
        blocks.extend(_recognize(document.path, needs_ocr, password, options, recognizer))
    blocks.sort(key=lambda block: (block.page, -block.y, 0 if block.kind == "heading" else 1))
    return blocks


def _trust_text(page: PageInfo) -> bool:
    if page.page_class in {"scan", "spread"}:
        return False
    return not (page.page_class == "ocr-layer" and alphanumeric_count(page) < 40)


def _recognize(
    path: Path,
    pages: list[PageInfo],
    password: str | None,
    options: ConvertOptions,
    recognizer: Recognizer | None,
) -> list[Block]:
    if options.recognizer == "none" and recognizer is None:
        raise RecognizerUnavailable("a page has no usable text layer and --recognizer none was set")
    engine = recognizer if recognizer is not None else _engine(options)
    spreads = [page for page in pages if page.page_class == "spread"]
    plain = [page.number + 1 for page in pages if page.page_class != "spread"]
    blocks: list[Block] = []
    work = _decrypted_copy(path, password) if password else path
    try:
        if plain:
            blocks.extend(engine.recognize(work, plain))
        for page in spreads:
            blocks.extend(_recognize_spread(engine, work, page))
    finally:
        if work != path:
            work.unlink(missing_ok=True)
    return blocks


def _engine(options: ConvertOptions) -> Recognizer:
    if options.recognizer == "docling":
        return DoclingRecognizer(gpu=options.gpu, chunk_pages=options.chunk_pages)
    return PaddleRecognizer(gpu=options.gpu, language=options.language)


def _decrypted_copy(path: Path, password: str | None) -> Path:
    reader = PdfReader(str(path))
    if reader.is_encrypted:
        reader.decrypt(password or "")
    writer = PdfWriter()
    writer.append(reader)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
        dest = Path(handle.name)
    with dest.open("wb") as fh:
        writer.write(fh)
    return dest


def _recognize_spread(engine: Recognizer, pdf_path: Path, page: PageInfo) -> list[Block]:
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        rendered = pdf[page.number].render(scale=150 / 72).to_pil()
    finally:
        pdf.close()
    width, height = rendered.size
    halves = (
        rendered.crop((0, 0, width // 2, height)),
        rendered.crop((width // 2, 0, width, height)),
    )
    blocks: list[Block] = []
    for half in halves:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            image_path = Path(handle.name)
        try:
            half.save(image_path, format="PNG")
            blocks.extend(engine.recognize_image(image_path, page.number + 1))
        finally:
            image_path.unlink(missing_ok=True)
    for block in blocks:
        block.page = page.number
    return blocks
