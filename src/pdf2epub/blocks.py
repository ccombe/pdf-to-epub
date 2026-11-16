"""Blocks the EPUB writer understands. A Recognizer and the text-layer path both emit these."""

from dataclasses import dataclass, field


@dataclass
class Line:
    page: int
    x: float
    y: float
    size: float
    text: str
    page_width: float
    page_height: float
    code: bool = False


@dataclass
class Block:
    kind: str
    text: str = ""
    level: int = 1
    page: int = 0
    source: str = "text"
    image: bytes | None = None
    image_ext: str = "png"
    image_href: str = ""
    alt: str = ""
    caption: str = ""
    y: float = 0
    left: float = 0
    bottom: float = 0
    right: float = 0


@dataclass
class OutlineEntry:
    title: str
    page: int
    level: int


@dataclass
class Chapter:
    title: str
    filename: str
    blocks: list[Block] = field(default_factory=list)
