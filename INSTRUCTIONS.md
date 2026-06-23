# Step-by-step: running the PDF Search API

## 1. Install Docker

- Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows/macOS) or Docker Engine (Linux).
- On Windows, accept the WSL2 prompt if asked, then restart Docker Desktop.
- Check it's running:
  ```bash
  docker --version
  docker info
  ```

## 2. Build the images

```bash
docker compose build
```

This builds the image used by both the `api` and `ingest` services (same Dockerfile, different commands).

## 3. Add the PDF files

- Download the documents from the shared Google Drive folder.
- Place them all in the `pdfs/` folder at the project root (flat, no subfolders).
- To add more PDFs later, just drop additional files into this same folder.

## 4. Run ingestion

```bash
docker compose run --rm ingest
```

This reads every PDF in `pdfs/`, extracts text, chunks it, embeds the chunks
locally on CPU, and writes the index to `data/index.faiss` and
`data/metadata.json`. The first run also downloads the embedding model
(a few hundred MB) — expect it to take a few minutes.

**Note:** this is a full rebuild every time — it re-processes *all* PDFs
currently in `pdfs/`, not just new ones.

## 5. Verify the index was created

```bash
ls data
```

You should see `index.faiss` and `metadata.json`.

## 6. Start the API

```bash
docker compose up
```

Add `-d` to run it in the background: `docker compose up -d`.

The API loads the index from `data/` once, at startup.

## 7. Test it

Health check:
```bash
curl -s http://localhost:8000/health
```
Expected: `{"status":"ok","index_loaded":true}`

Search:
```bash
curl -X POST http://localhost:8000/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Quelle est la position du document sur les politiques publiques ?", "top_k": 5}'
```

## 8. Adding more PDFs later / rebuilding the index

1. Drop the new PDF(s) into `pdfs/`.
2. Re-run ingestion:
   ```bash
   docker compose run --rm ingest
   ```
3. Restart the API so it reloads the new index (it only loads it once at startup):
   ```bash
   docker compose restart api
   ```

## 9. Stopping everything

```bash
docker compose down
```

## Troubleshooting

- **Port 8000 already in use**: stop whatever else is bound to it
  (`docker ps`, then `docker stop <container>`), or change the port mapping
  in `docker-compose.yml`.
- **`/search` returns 503**: no index was found at startup — run step 4,
  then restart the API (step 8.3).
- **A PDF produces 0 chunks**: it's likely a scanned/image-only PDF with no
  extractable text layer (this pipeline doesn't do OCR).
