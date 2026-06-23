from app.api.schemas import SearchResult
from app.embedder import Embedder
from app.vector_store import VectorStore


class SearchService:
    def __init__(self, embedder: Embedder, store: VectorStore, min_score: float = 0.0):
        self.embedder = embedder
        self.store = store
        self.min_score = min_score

    def search(self, query: str, top_k: int) -> list[SearchResult]:
        query_vector = self.embedder.embed([query])
        raw_results = self.store.search(query_vector, top_k)
        return [
            SearchResult(
                document_name=entry["document_name"],
                page_number=entry["page_number"],
                chunk_index=entry["chunk_index"],
                score=score,
                text=entry["text"],
            )
            for entry, score in raw_results
            if score >= self.min_score
        ]
