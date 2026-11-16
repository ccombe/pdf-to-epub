# PDF to EPUB

The language for turning Source PDFs into EPUBs a reader can reflow.

## Language

**Source PDF**:
A PDF file submitted for conversion. Its Pages need not share a Page class.
_Avoid_: document, input

**Page**:
One page of a Source PDF. The pipeline reads Pages. The EPUB does not keep them as the reader's pages.
_Avoid_: folio, leaf, slide

**Page class**:
The content kind of one Page.
_Avoid_: file type, document type

**Text layer**:
The Unicode characters stored on a Page, as distinct from its pixels.
_Avoid_: hidden text, OCR text

**Scan**:
A Page whose marks are an image and which has no text layer.
_Avoid_: image PDF, scanned PDF

**OCR-layer page**:
A Scan that also carries a text layer from an earlier OCR pass.
_Avoid_: searchable PDF, OCR-layer PDF, OCR'd PDF

**Born-digital page**:
A Page whose text was produced by an authoring tool.
_Avoid_: digital PDF, text PDF

**Tagged PDF**:
A Source PDF with a structure tree that records headings, reading order, and figure markers.
_Avoid_: accessible PDF, structured PDF

**Spread**:
A Page image that holds two facing pages.
_Avoid_: two-up, opening

**EPUB**:
A reflowable EPUB 3 package that passes EPUBCheck.
_Avoid_: ebook, book file

**Conversion**:
The production of one EPUB from one Source PDF.
_Avoid_: export, render

**Batch**:
A set of Conversions run as one CLI invocation. It does not prompt.
_Avoid_: job, queue

**Recognizer**:
A learned open-source model this project runs to recover characters and reading order from a Page.
_Avoid_: hosted OCR, OCR API, cloud vision
