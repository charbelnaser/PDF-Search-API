"""Ingestion CLI: reads PDFs from a folder, chunks and embeds them, and
persists a FAISS index + metadata to disk for the API to load later.

Usage:
    python -m app.ingest /path/to/pdf/folder
"""

import argparse
import logging
from pathlib import Path

from app.chunker import chunk_document
from app.config import Settings
from app.embedder import Embedder
from app.pdf_loader import extract_pages, iter_pdf_files
from app.vector_store import VectorStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ingest")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest PDF documents into a local vector index.")
    parser.add_argument("pdf_folder", type=Path, help="Path to the folder containing PDF files")
    parser.add_argument("--chunk-size", type=int, default=Settings.CHUNK_SIZE, help="Chunk size in characters")
    parser.add_argument("--chunk-overlap", type=int, default=Settings.CHUNK_OVERLAP, help="Overlap between chunks in characters")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.pdf_folder.is_dir():
        raise SystemExit(f"PDF folder not found: {args.pdf_folder}")

    pdf_files = iter_pdf_files(args.pdf_folder)
    if not pdf_files:
        logger.warning("No PDF files found in %s", args.pdf_folder)
        return

    logger.info("Loading embedding model %s (first run may download weights)...", Settings.EMBEDDING_MODEL)
    embedder = Embedder(Settings.EMBEDDING_MODEL)
    store = VectorStore(dimension=embedder.dimension)

    for pdf_path in pdf_files:
        logger.info("Processing %s", pdf_path.name)
        pages = extract_pages(pdf_path)
        if not pages:
            logger.warning("No extractable text in %s, skipping", pdf_path.name)
            continue

        chunks = chunk_document(pages, args.chunk_size, args.chunk_overlap)
        if not chunks:
            logger.warning("No chunks produced for %s, skipping", pdf_path.name)
            continue

        texts = [chunk.text for chunk in chunks]
        vectors = embedder.embed(texts)
        metadata = [
            {
                "document_name": chunk.document_name,
                "page_number": chunk.page_number,
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
            }
            for chunk in chunks
        ]
        store.add(vectors, metadata)
        logger.info("Added %d chunks from %s", len(chunks), pdf_path.name)

    if store.index.ntotal == 0:
        logger.warning("No chunks were indexed. Index not saved.")
        return

    store.save(Settings.INDEX_PATH, Settings.METADATA_PATH)
    logger.info("Saved index with %d vectors to %s", store.index.ntotal, Settings.INDEX_PATH)


if __name__ == "__main__":
    main()
