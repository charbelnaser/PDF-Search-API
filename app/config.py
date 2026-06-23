import os
from pathlib import Path


class Settings:
    DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
    INDEX_PATH = DATA_DIR / "index.faiss"
    METADATA_PATH = DATA_DIR / "metadata.json"

    EMBEDDING_MODEL = os.environ.get(
        "EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )

    CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", 800))
    CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", 150))

    MIN_SCORE = float(os.environ.get("MIN_SCORE", 0.4))
