"""Command line for batch PDF to EPUB conversion."""

import argparse
import sys
from pathlib import Path

from pdf2epub.convert import ConvertOptions, convert_batch


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    paths = _expand(args.inputs)
    if not paths:
        print("no PDF files to convert", file=sys.stderr)
        return 1
    options = ConvertOptions(
        output_dir=args.output,
        password=args.password,
        passwords=_load_passwords(args.passwords),
        title=args.title,
        author=args.author,
        language=args.language,
        force=args.force,
        recognizer=args.recognizer,
        gpu=args.gpu,
        chunk_pages=args.chunk_pages,
    )
    results = convert_batch(paths, options)
    failed = 0
    for result in results:
        print(result.as_json())
        if result.status == "error":
            failed += 1
            print(f"{result.source}: {result.error}", file=sys.stderr)
    return 1 if failed else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf2epub",
        description="Batch-convert PDFs into reflowable EPUB 3 files.",
    )
    parser.add_argument("inputs", nargs="+", type=Path, help="PDF files or directories of PDFs")
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("epub"), help="directory for EPUB files"
    )
    parser.add_argument("--password", help="password used for every encrypted PDF")
    parser.add_argument(
        "--passwords",
        type=Path,
        help="file of per-PDF passwords, one 'filename=password' line each",
    )
    parser.add_argument("--title", help="override the EPUB title")
    parser.add_argument("--author", help="override the EPUB creator")
    parser.add_argument("--language", default="en", help="EPUB language (default: en)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an EPUB that is already in the output directory",
    )
    parser.add_argument(
        "--recognizer",
        choices=("paddle", "docling", "none"),
        default="paddle",
        help="recognizer for pages with no usable text layer (default: paddle, the small PP-OCR models)",
    )
    parser.add_argument(
        "--gpu", action="store_true", help="ask the recognizer to use CUDA; CPU is the default"
    )
    parser.add_argument(
        "--chunk-pages", type=int, default=20, help="pages per recognizer job (default: 20)"
    )
    return parser


def _expand(inputs: list[Path]) -> list[Path]:
    found: list[Path] = []
    for path in inputs:
        if path.is_dir():
            found.extend(sorted(path.glob("*.pdf")))
        else:
            found.append(path)
    return found


def _load_passwords(path: Path | None) -> dict[str, str] | None:
    if path is None:
        return None
    mapping: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, secret = stripped.split("=", 1)
        mapping[name.strip()] = secret
    return mapping


if __name__ == "__main__":
    sys.exit(main())
