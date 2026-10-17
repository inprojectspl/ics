# ADR-0021: OCR of scanned PDF pages, local engine behind a provider interface

**Status:** Accepted, implemented 2026-09-28.
**Decision owners:** Owner.
**Scope:** `backend/app/ocr_local.py`, `backend/app/services/ocr/`,
`backend/app/jobs/ocr_worker.py`, `backend/app/jobs/tasks/ocr.py`,
`backend/app/routes/assets/ocr.py`, the `ocr` block of `/doc`, `/meta`,
`file-mcp`, `agent-view` and share resolve, the `document_ocr` table
(migration 0042), the `ocr-worker` compose service,
`frontend/src/components/PdfView/OcrStatus.tsx`, and the `ics-mcp` tool
`ics_asset_ocr`.

## Context

ADR-0013 left OCR out: a page without a text layer is marked
`_No text layer on this page (scanned image?)._`. Scanned PDFs turned out to
be common (regulatory decisions, signed contracts), sometimes hundreds of
pages and tens of MB. For agents and search such a document is empty.

## Problem

Which engine reads the pages, where and when it runs, how long it may take,
how a reader (human or agent) learns that the text is not there yet, and how
a second engine (a cloud API) can be added later without a rewrite.

## Decision

1. **Engine: PP-OCR (PaddleOCR models) through RapidOCR on the ONNX runtime,
   pages rendered by pdfium (`pypdfium2`).** All Apache-2.0 / BSD / MIT, CPU
   only, models shipped in the wheel (no download at runtime). Measured on a
   7-page French scan and synthetic Polish text: accents and Polish letters
   right, about 1.1 s per A4 page at 200 dpi on 2 threads, about 1.1 GB peak
   RSS (stable over 42 pages), about 3 GB address space. Line boxes are
   joined into lines and paragraphs by `layout_text`. Tables lose their grid
   (cells come out as lines); acceptable for search and reading.
   `opencv-python` is replaced by `opencv-python-headless` (uv override), so
   the slim image needs no libGL.
   Rejected for now:
   - VLM OCR models (PaddleOCR-VL, MinerU, olmOCR, dots.ocr): best quality
     and tables as Markdown, but they need a GPU the servers do not have.
   - Mistral OCR API as the default (EU, $1-4 per 1000 pages, zero data
     retention on request): good tables, but documents would leave the
     servers. It is offered as a second engine a reader picks per run
     (decision 9).
   - Tesseract: an apt package plus language packs in the image, weaker on
     degraded scans.
2. **Where: a child process per chunk of 100 pages, in a dedicated Arq
   queue served by the `ocr-worker` service.** The child (`python -m
   app.ocr_local`) imports no settings or database, runs under
   `RLIMIT_AS` (`ICS_OCR_MEMORY_BYTES`, 3 GB) and prints one JSON line per
   page. The parent waits at most `ICS_OCR_PAGE_TIMEOUT_SECONDS` (120) for
   the next line and bounds the whole run with `ICS_OCR_TIMEOUT_SECONDS`
   (3600); `ICS_OCR_MAX_PAGES` (1000) caps the pages read. The child's
   BLAS/OpenMP/OpenCV threads follow `ICS_OCR_THREADS` and glibc keeps two
   malloc arenas (`MALLOC_ARENA_MAX`): otherwise every CPU of the host adds
   a thread and an arena, and on a many-core machine the address space
   passes the limit while little memory is used. The queue is
   separate so a long scan never holds up outline rebuilds, and
   `ICS_OCR_CONCURRENCY` (1) documents are read at once; the container has
   a 1.5 GB limit.
3. **When: automatically after every write of a PDF version with pages
   without a text layer** (upload, new version, restore), unless
   `ICS_OCR_AUTO=0`, and on request (`POST /api/assets/{id}/ocr`, editor or
   higher) for the first run or a retry. `ICS_OCR_ENABLED=0` turns it off.
   Only `pdf_doc` supports OCR (`DocumentType.ocr_overlay`); every other
   kind has no OCR state and a request is `ocr_not_supported`: text
   formats already carry their text.
4. **State: one `document_ocr` row per asset version.** The text belongs to
   the bytes of one version, so a new version starts without a row
   (`not_requested`). States: `not_requested` (no row) -> `queued` ->
   `running` -> `done` | `failed` (with `error_code`); `done`, `failed` and
   `not_requested` go back to `queued` on a request. The row keeps the
   provider, `requested_at`, `started_at`, `finished_at`, a heartbeat, the
   attempt count and the page counts (`pages_total`, `pages_done`,
   `pages_recognized`). A job claims its row atomically (`queued` ->
   `running`), so a duplicate job is a no-op. Arq never retries; the sweeper
   (cron of the main worker, every minute) requeues a `running` row whose
   heartbeat is silent (a killed worker) until `ICS_OCR_MAX_ATTEMPTS`, then
   fails it as `ocr_interrupted`, and enqueues `queued` rows whose job was
   lost. Each attempt has its own job id.
5. **Result: `derived/v{n}/ocr.json`, merged by the derived files.** The
   recognized page texts are stored next to the version's derived files.
   `documents.ingest` overlays them on the extraction whenever it rebuilds
   `pdf.md` / `pdf.json`, so a lost derived file keeps its OCR text. OCR
   only fills pages without a text layer; a page with text is never
   replaced. An OCR page starts with `_Text recognized by OCR._`, a page
   where OCR found nothing reads `_No text layer on this page; OCR found no
   text._`. After a run on the current version the search blob, read size,
   prompt-injection scan, relations and outline are refreshed.
6. **Scans with a saved text layer: detected, OCR recommended, replaced
   only on request.** Scanners with built-in OCR save the page as an image
   with an invisible text layer (render mode 3) on top; that text is often
   poor (`notionole o déllbéré` for `nationale a délibéré`) and ICS cannot
   judge it. The extraction flags a page whose text is only invisible and
   which carries an image over at least 80% of its area
   (`hidden_text_pages`, `pages_with_hidden_text` in the state). Such pages
   are not queued automatically, since replacing text the file carries is
   the reader's call; the viewer and the agent notice recommend OCR, and a
   request (`replace_hidden_text` on the row) reads them and replaces the
   layer. Visible text is never replaced.
7. **Readers see the state, not only the text.** `/doc`, `/meta` (in the
   ETag), `file-mcp`, `agent-view`, share resolve and the PDF upload
   response carry an `ocr` block; `GET /api/assets/by-slug/{slug}/ocr` is
   the cheap poll. The viewer shows it above the pages (polling while
   active, "Run OCR again" for editors, a link to the text in the agent
   view), `ics_asset_read` adds an `ocr_notice` while pages have no text
   yet, and `ics_asset_ocr` shows or requests a run.
8. **Providers: `services/ocr/providers.py`** (registry; common types in
   `base.py`, the local engine in `local.py`). A provider has a `name`,
   `needs_api_key`, `markdown` (its page texts are Markdown) and
   `recognize(pdf, pages, settings, on_page, *, api_key) -> engine label`,
   reports each page through `on_page` and raises `OcrFailure(code)`. The
   run lifecycle is the same for every provider. `ICS_OCR_PROVIDER` is the
   engine of automatic runs, `ICS_OCR_PROVIDERS` the engines a request may
   name (listed in the `ocr` block as `providers`); the row records which
   one ran.
9. **Mistral OCR as the first cloud provider (`mistral`), key per run.**
   A reader picks it in the viewer and pastes their Mistral API key; the
   request (`POST /{id}/ocr` with `provider`, `api_key`) stores the key in
   Redis encrypted with a key derived from `ICS_SECRET_KEY`, for the run's
   time budget plus an hour, and the run deletes it when it ends. The key
   never reaches the database, the audit log, the job arguments or the
   logs; a run whose key expired fails as `ocr_api_key_missing`. The pages
   go to `/v1/ocr` (`ICS_OCR_MISTRAL_MODEL`, default `mistral-ocr-4-0`) in
   chunks of `ICS_OCR_MISTRAL_CHUNK_PAGES` (20), each cut into its own PDF
   by `app.pdf_split` in a child process and sent as a base64 data URL; a
   rate limit or a server error is retried twice. Mistral returns Markdown:
   tables and lists are kept, headings become bold (so they cannot break
   the `## Page N` sections) and image references are dropped. HTTP
   refusals map to codes (`ocr_api_key_invalid`, `ocr_provider_quota`,
   `ocr_provider_rate_limited`, ...). A temporary shape: a key stored per
   organisation or per user is the next step.

## Reactivation trigger

- Tables matter to users or agents: add a cloud provider (Mistral OCR with
  zero data retention and a DPA) or a VLM provider on a GPU host, chosen per
  request or per project.
- PDFs with a bad visible text layer (not a scan): add a forced OCR of all
  pages.
- OCR queue waits of more than a few minutes: raise `ICS_OCR_CONCURRENCY`
  with more CPU, or add OCR worker replicas.

## Consequences

- The backend virtualenv grows by about 275 MB (ONNX runtime, OpenCV, NumPy,
  models); the image grows more while the Dockerfile keeps the uv cache in
  the layer.
- One more service (`ocr-worker`) in every compose file; without it scans
  stay `queued` and the rest of ICS works as before.
- A scanned PDF becomes searchable and readable by agents minutes after the
  upload; until then readers are told why the text is missing.
- A second engine is a new class in `PROVIDERS`, no change to the state
  machine, the storage or the API.
