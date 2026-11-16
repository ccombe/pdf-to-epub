# pdf2epub

Batch-convert PDFs into reflowable EPUB 3. One PDF becomes one EPUB. The command does not prompt: a bad file is reported and the batch continues.

Born-digital pages and pages that already have a text layer are read from the PDF. Diagrams drawn as vectors are cropped and stored as PNG pictures. Typewriter listings become code blocks. Scans, and text layers that are too thin to trust, go through a local recognizer. The default is the small PaddleOCR mobile models (CPU). No hosted API is required.

## Install

[uv](https://docs.astral.sh/uv/) manages the environment, the lockfile, and the `pdf2epub` command.

```bash
uv sync
```

Scans need the OCR extra. Docling is optional and off unless you ask for it.

```bash
uv sync --extra ocr
uv sync --extra docling
```

## Convert

```bash
uv run pdf2epub book.pdf -o epub
uv run pdf2epub scans/ more.pdf -o epub
uv run pdf2epub book.pdf -o epub --recognizer none --title "Book title" --author "Author"
```

Each file prints one JSON object on stdout. The process exits 1 if any file failed. An EPUB that is already in the output directory is skipped unless you pass `--force`.

| Flag | Meaning |
| --- | --- |
| `-o`, `--output` | Directory for the EPUB files. Default: `epub`. |
| `--title`, `--author` | Override the title and creator. Otherwise they come from the PDF. |
| `--language` | EPUB language. Default: `en`. A value starting with `zh` selects the Chinese recognition model. |
| `--password` | Password used for every encrypted PDF. |
| `--passwords FILE` | One `filename=password` line per PDF. |
| `--recognizer` | `paddle` (default), `docling`, or `none`. |
| `--gpu` | Ask the recognizer to use CUDA. CPU is the default. |
| `--chunk-pages` | Pages per Docling job. Default: 20. |
| `--force` | Overwrite an EPUB that is already in the output directory. |

## What is kept

Headings, paragraphs, lists, figures, and captions. End-of-line hyphens are joined. Running headers, footers, and page numbers are dropped. The outline becomes the EPUB navigation document. The package is EPUB 3 (`version="3.0"`) with one stylesheet.

Words for the page kinds (scan, OCR-layer page, born-digital page, spread) are in [GLOSSARY.md](GLOSSARY.md).

## Development

```bash
uv sync
uv run ruff format
uv run ruff check
uv run ty check
uv run pytest
```

`uv.lock` pins the versions this tree is tested with. Python 3.12 or newer.
