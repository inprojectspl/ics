# ADR-0013: PDF as an asset kind, with its text served as Markdown

**Status:** Accepted, implemented 2026-09-26. The shared machinery moved to
`services/documents.py` with ADR-0014; OCR of scanned pages came with
ADR-0021; the viewer (point 4) was replaced by ADR-0022.
**Decision owners:** Owner.
**Scope:** `backend/app/pdf_extract.py`, `backend/app/pdf_markdown.py`,
`backend/app/services/pdf_assets.py`, `backend/app/routes/assets/pdf.py`,
the `pdf_doc` branches in `file-mcp`, `/doc`, share routes, search and
outline, `frontend/src/components/PdfView/`, and the `ics-mcp` tools
`ics_asset_create_pdf` / `ics_asset_replace_pdf`.

## Context

ICS stored Markdown notes, Markdown collections and HTML bundles. People
also share PDFs (reports, specifications, offers), and the main consumer of
ICS content besides the browser is an MCP agent, which cannot read a binary
PDF. For HTML bundles the backend already converts a page to Markdown for
MCP (`file-mcp?format=markdown`); a PDF needs the same.

## Problem

Five open questions from the work package: which library extracts the
text, when extraction runs, where its result is kept, how the browser shows
the PDF, and what the security scan looks for.

## Decision

1. **Library: pypdf (BSD-3).** Pure Python, typed, handles text, outline
   (bookmarks) and encryption, and walks the object graph for the scan.
   Rejected: PyMuPDF / pymupdf4llm (better layout, but AGPL, incompatible
   with the MIT license of ADR-0008), pdfminer.six / pdfplumber (MIT, better
   reading order, but slower and no simpler for our needs), docling and
   other ML converters (heavy models, GPU-friendly, out of proportion).
   pypdf's plain text is enough for search and for an agent to read; the
   Markdown is one `## Page N` section per page, with line starts escaped
   so extracted text cannot turn into headings or lists.
   Exception: a page where pypdf returns letter-spaced text (most words one
   or two letters long, typical of producers that place every glyph on its
   own and draw no spaces) is read again with pdfium, and word breaks come
   from the gaps between glyph boxes.
2. **Extraction runs at write time, in a child process.** Every write of a
   PDF version (upload, new version, restore) calls `pdf_assets.ingest`,
   which runs `python -m app.pdf_extract` with the PDF on stdin and limits
   on the command line (timeout 60 s, 2000 pages, 5 M characters, 2 GB
   address space where the OS allows). A crafted PDF can make a pure-Python
   parser loop or balloon; a thread cannot be stopped, a process can be
   killed. Synchronous extraction also validates the upload: a broken or
   password-protected PDF is refused before anything is stored
   (`invalid_pdf`, `pdf_encrypted`, `pdf_extraction_failed`). Rejected: an
   Arq background job (like the outline): search and MCP reads would show
   an empty document until the worker catches up, and validation would come
   after the asset already exists. Typical PDFs take well under a second.
3. **The result is a derived file, not a column.** `ingest` writes
   `{storage_prefix}/derived/v{n}/pdf.json` (page texts, bookmarks,
   findings). It sits outside the `v{n}/` tree, so it is not listed,
   downloaded or counted in the quota, and the version tree stays exactly
   what the user uploaded. Version bytes never change (ADR-0006), so the
   file never goes stale. Readers (`file-mcp`, `/doc`, share resolve,
   outline) read it through a helper that rebuilds a missing file from the
   stored PDF. `search_content` holds the page texts separated by form
   feeds, which lets `search-mcp` map a snippet to its page. Rejected: a
   JSONB column on `asset_versions` (a migration, and large rows in a table
   read on every version list).
4. **Viewer: PDF.js (Apache-2.0), lazily loaded.** The native `<embed>`
   renders differently per browser, shows only the first page on iOS Safari
   and runs its own plugin on the app origin. PDF.js renders pages to canvas
   inside the app, with no annotation, XFA or scripting layer, so JavaScript
   in a PDF never runs. The library (0.4 MB) and its worker (1.3 MB) load
   only when a PDF is opened. The raw PDF endpoints (`/by-slug/{slug}/pdf`,
   `/api/share/{token}/pdf`) answer with `Content-Disposition: attachment`,
   `nosniff` and a `sandbox` CSP, so opening one directly downloads it
   instead of rendering it on the app origin.
5. **Scan: active content, same report as HTML bundles.** The child process
   walks the object graph from the catalog (compressed object streams
   included) and reports `pdf_launch_action` (critical: starts a program),
   `pdf_javascript`, `pdf_embedded_file` and `pdf_xfa_form` (warn: the viewer
   does not run or show them, a desktop reader might). Findings use the
   HTML scanner's shape (`code` + `params`, `scan.<code>` messages), so the
   admin queue, `publication_blocked`, the 410 visitor gate and the findings
   UI work unchanged. Links are not reported: they are normal in documents.

Out of scope, as in the work package: OCR of scanned PDFs (a page without a
text layer is marked `_No text layer on this page (scanned image?)._`),
password-protected PDFs, editing, annotations and GitLab sync. Diffing two
PDF versions shows the file as binary; a diff of the extracted text is a
possible follow-up.

The frontend bundle budget (`frontend/scripts/check-bundle.mjs`) counts every
file in `dist/assets`, lazy chunks included. PDF.js adds 1.7 MB that no page
loads until a PDF is opened, so `MAX_DIST_BYTES` goes from 8 to 10 MiB and
`MAX_JS_FILES` from 150 to 160 (the worker is built as a `.js` chunk through
`?worker&url`, because servers often send `.mjs` as `application/octet-stream`,
which a module worker refuses). No eager chunk grew.

## Reactivation trigger

- Agents or users report poor reading order (multi-column layouts, tables):
  try pdfminer.six layout analysis inside the same child process.
- Scanned PDFs become common: OCR as a separate work package.
- Extraction time shows up in upload latency: move `ingest` to an Arq job
  and add a "text pending" state.

## Consequences

- One more child process per PDF write; its limits are settings
  (`ICS_PDF_MAX_BYTES`, `ICS_PDF_EXTRACT_TIMEOUT_SECONDS`,
  `ICS_PDF_EXTRACT_MAX_PAGES`, `ICS_PDF_EXTRACT_MAX_CHARS`,
  `ICS_PDF_EXTRACT_MEMORY_BYTES`).
- A new reader of PDF text must go through `services.documents` (since
  ADR-0014 the PDF is one entry of its registry: `load_meta`, `markdown`),
  never parse the PDF itself.
- `ics-mcp` gains `ics_asset_create_pdf` and `ics_asset_replace_pdf`;
  `ics_asset_read` returns the Markdown for `pdf_doc`.
