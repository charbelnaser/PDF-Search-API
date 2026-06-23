import numpy as np
from sentence_transformers import SentenceTransformer


class Embedder:
    """Wraps a local, CPU-runnable sentence-transformers model.

    Embeddings are L2-normalized so that inner product search (FAISS
    IndexFlatIP) is equivalent to cosine similarity.
    """

    def __init__(self, model_name: str):
        self.model_name = model_name
        self.model = SentenceTransformer(model_name)
        self.dimension = self.model.get_sentence_embedding_dimension()

    def embed(self, texts: list[str]) -> np.ndarray:
        embeddings = self.model.encode(
            texts,
            batch_size=32,
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return np.asarray(embeddings, dtype="float32")
