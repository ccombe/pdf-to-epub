import json
from pathlib import Path

from fpdf import FPDF
from pypdf import PdfReader, PdfWriter

from pdf2epub.blocks import Block
from pdf2epub.cli import main
from pdf2epub.convert import ConvertOptions, convert_file


class _FakeRecognizer:
    def recognize(self, pdf_path, page_numbers):
        return [
            Block(
                "paragraph", text="Recovered from the scan.", page=page_numbers[0] - 1, source="ocr"
            )
        ]

    def recognize_image(self, image_path, page_number):
        return [
            Block(
                "paragraph", text="Recovered from the spread.", page=page_number - 1, source="ocr"
            )
        ]


def test_born_digital_pdf_becomes_an_epub(tmp_path: Path):
    source = tmp_path / "story.pdf"
    _write_story(source)
    dest_dir = tmp_path / "out"
    result = convert_file(
        source,
        ConvertOptions(output_dir=dest_dir, recognizer="none"),
    )
    assert result.status == "ok", result.error
    epub = dest_dir / "story.epub"
    assert epub.exists()
    import zipfile

    with zipfile.ZipFile(epub) as archive:
        html = archive.read("OEBPS/chapter-01.xhtml").decode("utf-8")
        nav = archive.read("OEBPS/nav.xhtml").decode("utf-8")
    assert "Hello from the body of the book." in html
    assert "Chapter One" in nav


def test_batch_continues_and_resume_skips(tmp_path: Path, capsys):
    good = tmp_path / "good.pdf"
    _write_story(good)
    missing = tmp_path / "missing.pdf"
    out = tmp_path / "out"
    code = main([str(good), str(missing), "-o", str(out), "--recognizer", "none"])
    captured = capsys.readouterr()
    rows = [json.loads(line) for line in captured.out.splitlines()]
    assert code == 1
    assert rows[0]["status"] == "ok"
    assert rows[1]["status"] == "error"
    again = main([str(good), "-o", str(out), "--recognizer", "none"])
    skipped = json.loads(capsys.readouterr().out.strip())
    assert again == 0
    assert skipped["status"] == "skipped"


def test_encrypted_pdf_needs_the_password_from_the_batch(tmp_path: Path):
    source = tmp_path / "secret.pdf"
    _write_story(tmp_path / "plain.pdf")
    reader = PdfReader(str(tmp_path / "plain.pdf"))
    writer = PdfWriter()
    writer.append(reader)
    writer.encrypt("correct")
    with source.open("wb") as handle:
        writer.write(handle)
    locked = convert_file(source, ConvertOptions(output_dir=tmp_path / "a", recognizer="none"))
    assert locked.status == "error"
    assert locked.error is not None
    assert "password" in locked.error.lower()
    opened = convert_file(
        source,
        ConvertOptions(output_dir=tmp_path / "b", password="correct", recognizer="none"),
    )
    assert opened.status == "ok", opened.error


def test_scan_page_uses_the_recognizer(tmp_path: Path):
    source = tmp_path / "scan.pdf"
    _write_scan(source)
    result = convert_file(
        source,
        ConvertOptions(output_dir=tmp_path / "out", recognizer="docling"),
        recognizer=_FakeRecognizer(),
    )
    assert result.status == "ok", result.error
    import zipfile

    with zipfile.ZipFile(tmp_path / "out" / "scan.epub") as archive:
        html = archive.read("OEBPS/chapter-01.xhtml").decode("utf-8")
    assert "Recovered from the scan." in html


def _write_story(path: Path) -> None:
    pdf = FPDF()
    pdf.set_auto_page_break(False)
    pdf.add_page()
    pdf.set_font("Helvetica", size=24)
    pdf.text(20, 30, "Chapter One")
    pdf.set_font("Helvetica", size=12)
    pdf.text(20, 50, "Hello from the body of the book.")
    for index in range(3):
        pdf.add_page()
        pdf.set_font("Helvetica", size=10)
        pdf.text(20, 12, "Running Header")
        pdf.set_font("Helvetica", size=12)
        pdf.text(20, 40, f"Body paragraph on page {index + 2}.")
        pdf.text(100, 280, str(index + 2))
    pdf.output(path)


def _write_scan(path: Path) -> None:
    from io import BytesIO

    from PIL import Image

    image = Image.new("RGB", (1200, 1600), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    png = tmp_image(path.parent / "page.png", buffer.getvalue())
    pdf = FPDF(unit="pt", format=(612, 792))
    pdf.add_page()
    pdf.image(str(png), x=0, y=0, w=612, h=792)
    pdf.output(path)


def tmp_image(path: Path, blob: bytes) -> Path:
    path.write_bytes(blob)
    return path
