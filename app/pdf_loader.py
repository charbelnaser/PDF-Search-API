import logging
from dataclasses import dataclass
from pathlib import Path

import ftfy
import pdfplumber

logger = logging.getLogger(__name__)


@dataclass
class PageText:
    document_name: str
    page_number: int
    text: str


def iter_pdf_files(folder: Path) -> list[Path]:
    return sorted(folder.glob("*.pdf"))


def extract_pages(pdf_path: Path) -> list[PageText]:
    pages: list[PageText] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception:
                logger.exception("Failed to extract text from %s page %d", pdf_path.name, page_number)
                continue
            text = ftfy.fix_text(text)
            if text.strip():
                pages.append(PageText(document_name=pdf_path.name, page_number=page_number, text=text))
    return pages
