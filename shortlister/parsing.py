"""CV file -> plain text. Parse failures never stop a batch; they return an error
string so the candidate is marked low-confidence (G1.2) and listed in NOTES.md."""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

SUPPORTED = {".pdf", ".docx", ".txt", ".md", ".rtf", ".odt", ".doc"}
MIN_USEFUL_CHARS = 200  # below this a CV is treated as sparse


@dataclass
class Parsed:
    text: str
    error: str | None = None
    note: str | None = None  # e.g. "read with OCR"

    @property
    def sparse(self) -> bool:
        return len(self.text.strip()) < MIN_USEFUL_CHARS


def parse_file(path: Path) -> Parsed:
    ext = path.suffix.lower()
    try:
        if ext == ".pdf":
            text = _pdf(path)
            if len(text.strip()) < MIN_USEFUL_CHARS:
                ocr = _ocr_pdf(path)
                if ocr and len(ocr.strip()) > len(text.strip()):
                    return Parsed(_normalise(ocr), note="scanned PDF read with OCR; check quotes against the original")
        elif ext == ".docx":
            text = _docx(path)
        elif ext in (".txt", ".md"):
            text = path.read_text(encoding="utf-8", errors="replace")
        elif ext == ".rtf":
            text = _rtf(path.read_text(encoding="utf-8", errors="replace"))
        elif ext == ".odt":
            text = _odt(path)
        elif ext == ".doc":
            text = _legacy_doc(path)
        else:
            return Parsed("", f"unsupported file type {ext}")
    except Exception as exc:  # noqa: BLE001 - any parser failure is a soft failure
        return Parsed("", f"{type(exc).__name__}: {exc}")
    text = _normalise(text)
    if not text.strip():
        return Parsed("", "no extractable text (scanned image or empty file?)")
    return Parsed(text)


def _normalise(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def ocr_available() -> bool:
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:  # noqa: BLE001 - missing package or missing Tesseract binary
        return False


def _ocr_pdf(path: Path) -> str | None:
    """Local OCR (Tesseract) for scanned PDFs. Runs on this machine only: the unredacted
    image never goes to the AI. Returns None when Tesseract isn't installed."""
    if not ocr_available():
        return None
    import io

    import pytesseract
    from PIL import Image
    from pypdf import PdfReader

    out = []
    for page in PdfReader(str(path)).pages:
        for img in page.images:
            try:
                out.append(pytesseract.image_to_string(Image.open(io.BytesIO(img.data))))
            except Exception:  # noqa: BLE001
                continue
    return "\n".join(out)


def _docx(path: Path) -> str:
    import docx

    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(str(path))
    parts = []
    # Walk the body in document order: many CVs put the name/contact block in a table.
    for el in d.element.body.iterchildren():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "p":
            parts.append(Paragraph(el, d).text)
        elif tag == "tbl":
            for row in Table(el, d).rows:
                cells = []
                for c in row.cells:
                    if c.text not in cells:  # merged cells repeat their text
                        cells.append(c.text)
                parts.append(" | ".join(cells))
    # Headers often hold the name / contact line; include them so redaction sees them.
    for section in d.sections:
        for p in section.header.paragraphs:
            parts.insert(0, p.text)
    return "\n".join(parts)


def _rtf(raw: str) -> str:
    raw = re.sub(r"\\par[d]?", "\n", raw)
    raw = re.sub(r"\\'[0-9a-f]{2}", "", raw)
    raw = re.sub(r"\\[a-z]+-?\d* ?", "", raw)
    return re.sub(r"[{}]", "", raw)


def _odt(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("content.xml").decode("utf-8", errors="replace")
    xml = re.sub(r"</text:p>|<text:line-break/>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml)


def _legacy_doc(path: Path) -> str:
    """Best effort for old binary .doc: pull runs of printable text."""
    data = path.read_bytes()
    chunks = re.findall(rb"(?:[\x20-\x7e]\x00){4,}", data)  # UTF-16LE runs
    text = "\n".join(c.decode("utf-16le", errors="ignore") for c in chunks)
    if len(text) < MIN_USEFUL_CHARS:
        raise ValueError("legacy .doc could not be read; save as .docx or .pdf")
    return text
