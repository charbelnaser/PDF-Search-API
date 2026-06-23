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

## Installing Docker

You need Docker installed and running before you can build or run the image.

**Windows / macOS**
1. Download and install [Docker Desktop](https://www.docker.com/products/docker-desktop/).
2. On Windows, Docker Desktop requires WSL2 — the installer will prompt you to enable it if it isn't already (you may need to restart once).
3. Launch Docker Desktop and wait for it to report "Engine running" (whale icon in the system tray / menu bar).
4. Verify from a terminal:
   ```bash
   docker --version
   docker info
   ```
   `docker info` should return cluster/engine details without errors. If it errors with something like "cannot connect to the Docker daemon", Docker Desktop isn't running yet — start it and wait a few seconds.

**Linux**
Follow the [official install guide](https://docs.docker.com/engine/install/) for your distribution (e.g. `apt-get install docker.io` on Debian/Ubuntu, or the Docker Engine repo for the latest version), then start the daemon: `sudo systemctl enable --now docker`.

## Running with Docker

```bash
# Build the image
docker build -t pdf-search-api .

# 1. Download the PDFs locally, e.g. into ./pdfs

# 2. Run ingestion inside a container, mounting both the PDFs (read-only)
#    and the data/ folder (where the index gets persisted)
docker run --rm \
  -v "$(pwd)/pdfs:/pdfs:ro" \
  -v "$(pwd)/data:/app/data" \
  pdf-search-api \
  python -m app.ingest /pdfs

# 3. Verify the index was created
ls data/   # expect index.faiss and metadata.json

# 4. Start the API, mounting the same data/ folder so it can load the index
docker run --rm -p 8000:8000 \
  -v "$(pwd)/data:/app/data" \
  pdf-search-api

# 5. Call the search endpoint
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Quelle est la position du document sur les politiques publiques ?", "top_k": 5}'
```

On Windows PowerShell, replace `$(pwd)` with `${PWD}`.

### Rebuilding the index

If the PDF folder changes, just re-run the ingestion command (step 2 above).
It overwrites `data/index.faiss` and `data/metadata.json` from scratch — there
is no incremental update. Restart the API container afterwards so it picks up
the new index (it's loaded once at startup).

### Configuration

All tunables are environment variables with sane defaults (see `app/config.py`):

| Variable | Default | Purpose |
|---|---|---|
| `DATA_DIR` | `data` | Where the index/metadata are read from and written to |
| `EMBEDDING_MODEL` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Local embedding model |
| `CHUNK_SIZE` | `800` | Characters per chunk |
| `CHUNK_OVERLAP` | `150` | Overlap between consecutive chunks |

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
  ]
}
```

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
- **Vector store**: FAISS `IndexFlatIP` (exact search, no approximation) with
  L2-normalized embeddings, so inner product == cosine similarity. Flat
  index is the simplest correct choice at the scale of a few PDFs; it
  doesn't scale to millions of vectors, but that's out of scope here.
- **Index loading**: the API loads the index once at startup (not per
  request) for performance; it must be restarted after re-ingestion.
- **Single Dockerfile**: same image runs both the ingestion CLI (via
  `docker run ... python -m app.ingest ...`) and the API (default `CMD`),
  sharing code and dependencies. `data/` is the contract between them.

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
