import json
from pathlib import Path

import faiss
import numpy as np


class VectorStore:
    """Thin wrapper around a FAISS IndexFlatIP plus a parallel metadata list.

    Metadata entry at position i always describes the vector at row i of the
    FAISS index. There is no separate ID mapping: list position is the ID.
    """

    def __init__(self, dimension: int):
        self.dimension = dimension
        self.index = faiss.IndexFlatIP(dimension)
        self.metadata: list[dict] = []

    def add(self, vectors: np.ndarray, metadata: list[dict]) -> None:
        if vectors.shape[0] != len(metadata):
            raise ValueError("Number of vectors must match number of metadata entries")
        self.index.add(vectors)
        self.metadata.extend(metadata)

    def search(self, query_vector: np.ndarray, top_k: int) -> list[tuple[dict, float]]:
        if self.index.ntotal == 0:
            return []
        top_k = min(top_k, self.index.ntotal)
        scores, indices = self.index.search(query_vector, top_k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:
                continue
            results.append((self.metadata[idx], float(score)))
        return results

    def save(self, index_path: Path, metadata_path: Path) -> None:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, str(index_path))
        metadata_path.write_text(json.dumps(self.metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, index_path: Path, metadata_path: Path) -> "VectorStore":
        index = faiss.read_index(str(index_path))
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        store = cls(dimension=index.d)
        store.index = index
        store.metadata = metadata
        return store
