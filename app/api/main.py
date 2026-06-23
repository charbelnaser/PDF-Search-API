import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from app.api.schemas import SearchRequest, SearchResponse
from app.api.search_service import SearchService
from app.config import Settings
from app.embedder import Embedder
from app.vector_store import VectorStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("api")

service: SearchService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global service
    if Settings.INDEX_PATH.exists() and Settings.METADATA_PATH.exists():
        embedder = Embedder(Settings.EMBEDDING_MODEL)
        store = VectorStore.load(Settings.INDEX_PATH, Settings.METADATA_PATH)
        service = SearchService(embedder, store)
        logger.info("Loaded index with %d vectors from %s", store.index.ntotal, Settings.INDEX_PATH)
    else:
        service = None
        logger.warning(
            "No index found at %s. Run the ingestion CLI before calling /search.",
            Settings.INDEX_PATH,
        )
    yield


app = FastAPI(title="PDF Search API", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "index_loaded": service is not None}


@app.post("/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Index not loaded. Run the ingestion CLI first, then restart the API.",
        )
    results = service.search(request.query, request.top_k)
    return SearchResponse(query=request.query, results=results)
