# ADR-0014: Word and OpenDocument text as an asset kind, served as Markdown

**Status:** Accepted, implemented 2026-09-26.
**Decision owners:** Owner.
**Scope:** `backend/app/office_extract.py`, `backend/app/services/documents.py`
(the document registry shared with PDFs), `backend/app/services/office_assets.py`,
`POST /api/assets/document`, the `office_doc` branches in the viewer,
`frontend/src/components/OfficeDocument/`, and the `ics-mcp` tools
`ics_asset_create_document` / `ics_asset_replace_document`.

## Context

After PDFs (ADR-0013) the next most common files people want to share are
Word documents: offers, specifications, tender attachments, mostly `.docx`,
sometimes `.odt` from LibreOffice and old `.doc` files. As with PDFs, the
main requirement is that an MCP agent can read the document as Markdown.

## Problem

Which libraries convert the three formats, how the browser shows the
document, and how the PDF machinery (child process, derived files, scan)
is shared instead of copied.

## Decision

1. **Conversion per format, all in one child process
   (`python -m app.office_extract`).** The format is detected from the
   content (a ZIP with `word/document.xml`, a ZIP whose `mimetype` is an
   ODF text document, or an OLE file with a `WordDocument` stream), so a
   misnamed file still works and a renamed executable does not.
   - `.docx`: **mammoth** (BSD-2) to HTML, then the existing
     `html_to_markdown` (markdownify). mammoth maps heading styles, lists,
     tables and footnotes, and its image hook lets us count images without
     ever reading them. Rejected: python-docx (MIT, lower level: lists,
     footnotes and style mapping would be ours to write), pandoc (a
     binary in the image, GPL), LibreOffice headless (hundreds of MB in the
     image, slow start, a large attack surface).
   - `.odt`: a small walker over `content.xml` with lxml (no DTD, no
     entities, no network) producing HTML for the same `html_to_markdown`.
     Rejected: odfpy (unmaintained since 2020, and its `odf2xhtml` pulls
     in styling we drop anyway).
   - `.doc`: **olefile** (BSD) plus our own reader of the piece table
     ([MS-DOC] 2.4.1): the main text with paragraphs and table rows
     (cell and row marks), field results kept and field codes dropped.
     Styles are not parsed, so headings of a `.doc` come out as plain
     paragraphs. Rejected: antiword and catdoc (GPL binaries, abandoned),
     LibreOffice (as above), textract (wraps those binaries).
2. **Limits.** The child has a timeout and an address-space limit as for
   PDFs, and a ZIP is refused before unpacking when it declares more than
   `ICS_OFFICE_MAX_UNZIPPED_BYTES` (zip bomb) or 5000 entries. Password
   protected documents are refused (`office_encrypted`).
3. **One document registry for PDFs and Office files.**
   `services/documents.py` holds a `DocumentType` per kind (child module,
   extensions, error codes, limits, how to build the Markdown body, search
   text and counts); upload, new version, restore, `file-mcp`, `/doc`,
   share resolve, outline and scan ask the registry by `asset.kind`. The
   derived files are `{stem}.json` and `{stem}.md` next to the version
   (`pdf.*` for PDFs, `doc.*` for Office documents), outside the version
   tree and the quota, exactly as in ADR-0013.
4. **Viewer: the converted Markdown, rendered like a Markdown document.**
   `/doc` returns `html` rendered from the Markdown body through the same
   renderer, sanitizer and cache (`render_cache.render_document`) as
   `md_single`, plus `document: {source_format, images}`. The browser never
   receives the original file except as a download. Rejected: docx-preview
   and similar client renderers (only `.docx`, a second HTML injection path
   to sanitize, and it would differ from what agents read).
5. **Scan.** `office_macros` (a VBA project found by its content type or
   `vbaProject` relationship whatever its name, form-field entry/exit
   macros, ODF `Basic/`/`Scripts/` parts, any ODF script-namespace element
   such as an event listener, `text:execute-macro` and `macro:` /
   `vnd.sun.star.script:` URLs (CVE-2019-9848), or `Macros`/`_VBA_PROJECT_CUR`
   in a `.doc`) and `office_remote_template`
   (an external `attachedTemplate`/`oleObject`/`frame`/`subDocument`
   relationship, or a `.doc` attached template from SttbfAssoc, pointing at
   http(s), UNC or `file://host`: the remote template injection technique)
   are critical and hold the document for admin review, as is `office_dde`
   (a DDE/DDEAUTO field instruction in a `.docx` or `.doc`, or an ODF DDE
   connection: it runs a command when the document opens or updates).
   Remote targets include `mhtml:`-wrapped URLs (CVE-2021-40444).
   Embedded objects (found by path, relationship type, including altChunk,
   or content type) and
   other external references are warnings: linked images, other external
   relationships and remote INCLUDEPICTURE/INCLUDETEXT/LINK fields of a
   `.docx`, and `xlink:href`
   targets of ODF images, objects and sections that point at http(s), UNC
   or `file://` (loaded on open; a UNC path also leaks the NTLM hash).
   Hyperlinks are not reported. A held document is withheld from guests on
   every path that carries its content: `/doc`, `/download`, `/pdf`,
   share resolve and, for read-only roles, `file-mcp`.

Out of scope: editing in the browser, images (never extracted; marked
`[image]` in the text), OCR, password-protected files, spreadsheets and
presentations.

## Reactivation trigger

- Users rely on `.doc` headings: parse the style sheet (STSH) and paragraph
  properties to recover heading levels.
- Documents with meaningful images: extract them as assets of the version
  and link them from the Markdown.

## Consequences

- New settings: `ICS_OFFICE_MAX_BYTES`, `ICS_OFFICE_MAX_UNZIPPED_BYTES`,
  `ICS_OFFICE_CONVERT_TIMEOUT_SECONDS`, `ICS_OFFICE_CONVERT_MAX_CHARS`,
  `ICS_OFFICE_CONVERT_MEMORY_BYTES`.
- A new converted-document kind is a new `DocumentType` plus its child
  module; callers do not change.
- The converter's code is not part of the render cache fingerprint: a
  converter change reaches old versions only when their derived files are
  rebuilt.
