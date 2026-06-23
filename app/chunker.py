from dataclasses import dataclass

from app.pdf_loader import PageText


@dataclass
class Chunk:
    document_name: str
    page_number: int
    chunk_index: int
    text: str


def split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Fixed-size character chunking with overlap, on whitespace-normalized text.

    Simple by design: good enough for short, real-world PDFs and keeps the
    ingestion pipeline easy to reason about. See README for trade-offs.
    """
    normalized = " ".join(text.split())
    if not normalized:
        return []

    pieces = []
    start = 0
    length = len(normalized)
    while start < length:
        end = min(start + chunk_size, length)
        pieces.append(normalized[start:end])
        if end == length:
            break
        start = end - overlap
    return pieces


def chunk_document(pages: list[PageText], chunk_size: int, overlap: int) -> list[Chunk]:
    """Chunk all pages belonging to a single document. chunk_index resets per document."""
    chunks: list[Chunk] = []
    chunk_index = 0
    for page in pages:
        for piece in split_text(page.text, chunk_size, overlap):
            chunks.append(
                Chunk(
                    document_name=page.document_name,
                    page_number=page.page_number,
                    chunk_index=chunk_index,
                    text=piece,
                )
            )
            chunk_index += 1
    return chunks
