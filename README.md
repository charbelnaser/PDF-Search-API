# PDF Search API

A small local search engine over a collection of PDF documents (in French).
Two pieces:

1. **Ingestion CLI** (`app/ingest.py`) — reads PDFs from a folder, extracts
   text, chunks it, embeds the chunks with a local CPU model, and persists a
   FAISS index + metadata to disk.
2. **FastAPI server** (`app/api/main.py`) — loads the persisted index at
   startup and exposes `POST /search` for similarity search over the chunks.

## Project structure

```
app/
  config.py          # paths, model name, chunk size — overridable via env vars
  pdf_loader.py       # PDF -> per-page text (pdfplumber)
  chunker.py           # per-page text -> fixed-size overlapping chunks
  embedder.py          # sentence-transformers wrapper (local, CPU)
  vector_store.py      # FAISS IndexFlatIP + parallel metadata list, save/load
  ingest.py            # CLI entrypoint: python -m app.ingest <pdf_folder>
  api/
    main.py            # FastAPI app, loads index at startup
    schemas.py         # request/response models
    search_service.py  # embed query + search the store
data/                  # persisted index.faiss + metadata.json (volume-mounted)
Dockerfile
docker-compose.yml     # api + ingest services, both built from the Dockerfile
requirements.txt
```

## Running locally without Docker

```bash
python -m venv .venv && . .venv/Scripts/activate   # or source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt

# 1. Download the PDFs from the shared Google Drive folder into a local folder, e.g. ./pdfs

# 2. Run ingestion (builds data/index.faiss + data/metadata.json)
python -m app.ingest ./pdfs

# 3. Start the API
uvicorn app.api.main:app --reload
```


## Running with Docker

```bash
# 1. Build the image
docker compose build

# 2. Place your PDFs in ./pdfs, then ingest them (builds data/index.faiss + data/metadata.json)
#    Skip this step if you've already ingested and nothing in ./pdfs changed.
docker compose run --rm ingest

# 3. Start the API (loads the index from ./data), detached
docker compose up -d
```

The API is then available at `http://localhost:8000` (Swagger UI at `/docs`).

Run with `-d` (detached) rather than attached to your terminal: the embedding
model takes several seconds to load on startup, and if `docker compose up`
is left attached and the terminal is interrupted (Ctrl+C, closed window)
during that window, Compose escalates to `SIGKILL` and the container dies
mid-startup. Check logs/status with `docker compose logs -f api` /
`docker compose ps`, and stop it with `docker compose down`.

Test it:
```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Quelle est la position du document sur les politiques publiques ?", "top_k": 5}'
```

### Adding new data / rebuilding the index

If you add or change PDFs in `./pdfs`:
```bash
docker compose run --rm ingest
docker compose restart api
```
Ingestion always rebuilds `data/index.faiss` and `data/metadata.json` from
scratch from everything currently in `./pdfs` — there's no incremental
update. The API only loads the index once at startup, so it must be
restarted to pick up the new one.

### Configuration

All tunables are environment variables with sane defaults (see `app/config.py`):

| Variable | Default | Purpose |
|---|---|---|
| `DATA_DIR` | `data` | Where the index/metadata are read from and written to |
| `EMBEDDING_MODEL` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Local embedding model |
| `CHUNK_SIZE` | `800` | Characters per chunk |
| `CHUNK_OVERLAP` | `150` | Overlap between consecutive chunks |
| `MIN_SCORE` | `0.4` | Minimum cosine similarity for a result to be returned by `/search` |

## API

### `POST /search`

Request:
```json
{ "query": "Quelle est la position du document sur les politiques publiques ?", "top_k": 5 }
```

Response:
```json
{
  "query": "Quelle est la position du document sur les politiques publiques ?",
  "results": [
    {
      "document_name": "example.pdf",
      "page_number": 3,
      "chunk_index": 12,
      "score": 0.82,
      "text": "Contenu du passage correspondant..."
    }
  ],
  "message": null
}
```

If no chunk scores at or above `MIN_SCORE`, `results` is an empty list and
`message` is set to `"No relevant results found for this query."` instead of
silently returning low-confidence noise.

`score` is a cosine similarity in `[-1, 1]` (embeddings are L2-normalized and
FAISS uses inner-product search), higher is more relevant.

### `GET /health`

Returns `{"status": "ok", "index_loaded": true|false}` — useful to check
whether the API found a persisted index at startup.

## Design decisions

- **Chunking**: fixed-size character windows (800 chars, 150 overlap) on
  whitespace-normalized page text, rather than sentence- or token-aware
  splitting. It's simple, deterministic, and good enough for retrieval at
  this scale; it can occasionally cut mid-sentence.
- **Chunk identity**: `chunk_index` resets to 0 per document and increases in
  reading order (page by page), so `(document_name, chunk_index)` uniquely
  identifies a chunk.
- **Vector store**: FAISS `IndexFlatIP` (exact search, no approximation).
  `IndexFlatIP` computes a plain inner product (dot product), which is *not*
  cosine similarity in general — it only becomes cosine similarity because
  `Embedder.embed()` calls `model.encode(..., normalize_embeddings=True)`,
  L2-normalizing every vector (chunks at ingestion time, queries at search
  time) to unit length. For unit vectors, `dot(a, b) == cos(θ)`, so the
  `score` returned by `/search` is an exact cosine similarity, not an
  approximation. `IndexFlatIP` returns the `top_k` vectors with the
  *highest* dot product, sorted descending (best match first) — the
  opposite convention from a distance-based index like `IndexFlatL2`, where
  *lower* is better. "Highest = best" lines up directly with cosine
  similarity (1.0 = identical direction, -1.0 = opposite), so no score
  inversion is needed anywhere in the search code. Flat index is the
  simplest correct choice at the scale of a few PDFs; it doesn't scale to
  millions of vectors, but that's out of scope here.
- **Metadata storage**: `data/metadata.json` and `data/index.faiss` are
  linked purely by list position, not by an explicit ID field. `VectorStore.add()`
  always appends to the FAISS index and the metadata list together, so the
  vector at row `i` always corresponds to `metadata[i]`. A FAISS search
  returns row numbers (`idx`); `self.metadata[idx]` is what turns "row 47
  scored highest" into an actual document name, page number, and text.
- **Minimum score threshold**: vector similarity search has no concept of
  "no relevant result" — it always returns the `top_k` closest chunks, even
  if none of them actually answer the query, just with low scores.
  `SearchService` filters out results below `MIN_SCORE` (default `0.3`) so
  `/search` returns an empty `results` list instead of low-confidence noise
  when nothing in the corpus is a real match.
- **Index loading**: the API loads the index once at startup (not per
  request) for performance; it must be restarted after re-ingestion.
- **Single Dockerfile**: the same image runs both the ingestion CLI and the
  API; `docker-compose.yml` defines them as two services (`ingest`, `api`)
  built from that one image, sharing code and dependencies. `data/` is the
  contract between them.
- **Embedding model baked into the image at build time**: the `Dockerfile`
  runs `SentenceTransformer(...)` once during `docker build` so the ~470MB
  model is downloaded into the image layer, instead of every fresh container
  re-downloading it from Hugging Face at startup. This was a real failure
  mode during development — on a restrictive network, the runtime download
  stalled partway through, leaving the container unable to serve requests
  for several minutes. Baking it in trades a slightly longer/heavier image
  for a startup that needs no network access at all (~5s instead of
  minutes, or an indefinite hang on a bad network).

## Solution Review

**Main limitations**
- No incremental ingestion — re-running it rebuilds the whole index from
  scratch, which is fine for a handful of PDFs but won't scale.
- Fixed-size chunking ignores document structure (titles, paragraphs,
  tables), so chunk boundaries can split sentences or merge unrelated ideas.
- The API loads the index only at startup; it won't notice a re-ingestion
  without a restart.
- No authentication, rate limiting, or pagination on `/search`.
- No automated tests.

**Where search quality may be poor**
- Scanned/image-only PDFs with no extractable text layer will silently
  produce zero chunks for that document (pdfplumber only reads embedded
  text).
- Tables, multi-column layouts, headers/footers, and footnotes often get
  extracted out of visual order or merged into surrounding text, which can
  pollute chunk content.
- Very short or very generic queries will return semantically "close but not
  useful" passages, since this is pure embedding similarity with no
  keyword/BM25 signal or reranking.
- Cross-references that span chunk boundaries (e.g., "as stated above") lose
  context since chunks are retrieved independently.

**Assumptions made**
- All input PDFs are placed in a single flat local folder (no recursive
  subfolders) before running ingestion.
- "Local open-source model runnable on CPU" is satisfied by
  sentence-transformers; no GPU is assumed or required.
- A handful of PDFs (not a large corpus) — hence the choice of an exact flat
  FAISS index over an approximate one.
- It's acceptable for the API to return 503 on `/search` if ingestion hasn't
  been run yet, rather than failing at startup.

**What I'd improve with more time**
- Smarter chunking (sentence-aware, or token-based using the embedding
  model's tokenizer) to avoid mid-sentence cuts.
- Deduplicate near-identical chunks (common with repeated headers/footers in
  parliamentary documents).
- Add a hybrid retrieval step (BM25 + embeddings) or a lightweight reranker.
- Add automated tests for chunking, the store, and the API contract.
- Expose ingestion as an API-triggered job (with status polling) instead of
  a separate CLI-only step, for an easier reviewer/demo experience.

**For a production-ready version**
- Swap the flat FAISS index for an approximate index (HNSW/IVF) or a managed
  vector database for scale and metadata filtering.
- Move ingestion to an async pipeline (queue + workers) decoupled from the
  API process, with incremental/idempotent updates per document.
- Add observability (structured logging, request tracing, query/result
  metrics) and basic auth/rate limiting on the API.
- Add a re-ranking or LLM-based answer-synthesis layer on top of retrieval,
  if the product requires direct answers rather than passages.
