# ADR-0022: PDF reader on pdf.js' viewer components, with full screen

**Status:** Accepted, implemented 2026-09-28. Replaces point 4 of ADR-0013
(the canvas-only page renderer).
**Decision owners:** Owner.
**Scope:** `frontend/src/components/PdfView/` (`PdfReader`, `PdfToolbar`,
`useViewerGestures`, `pdfjs.ts`), the `pdfjsAssets` plugin in
`frontend/vite.config.ts`.

## Context

ADR-0013 drew each page into a canvas and nothing else. A PDF could be
read, but not used: no text selection or copy, no search, no links, a fixed
width with no zoom, no way to give the document the whole screen on a
phone. Scans with JBIG2 images (common for black and white scanners) came
out blank, because pdf.js 6 decodes JBIG2 and JPEG 2000 with WebAssembly
modules it loads from `wasmUrl`, which was not set; CMaps and the standard
fonts were missing the same way.

## Problem

Which reader to build on, how it goes full screen on desktop and mobile,
and how pdf.js gets its run-time files.

## Decision

1. **pdf.js' own viewer components (`pdfjs-dist/web/pdf_viewer`), the
   engine of Firefox's reader.** `PDFViewer` draws only the pages near the
   viewport and redraws them sharp at every zoom (tiled above the 16 Mpx
   canvas limit of iOS), `TextLayerBuilder` makes the text selectable,
   `PDFFindController` searches it with highlights, `PDFLinkService`
   follows internal links and opens external ones in a new tab
   (`noopener noreferrer nofollow`). Annotations render read-only
   (`AnnotationMode.ENABLE`, no form editing, no annotation editor); no
   scripting manager and no XFA are mounted, so document JavaScript still
   never runs. The library is already a dependency: no second engine.
   Rejected:
   - react-pdf: a per-page wrapper over the same pdf.js; virtualisation,
     search and zoom would have to be written on top.
   - EmbedPDF: a second engine (pdfium in WebAssembly, several MB) and a
     young ecosystem.
   - Commercial viewers (Nutrient, Syncfusion, KendoReact): licences.
   - The browser's own viewer (`<iframe>`, `<embed>`): first page only on
     iOS Safari, a download on some Android browsers, and a plugin running
     on the app origin (ADR-0013).
   Every one of these draws pages as bitmaps; what makes a reader usable is
   the text layer, search, links and redrawing on zoom.
2. **Toolbar and gestures.** Page field and previous / next, zoom out / in
   with the level, fit to width, search (Enter / Shift+Enter, match count),
   download and full screen. Pinch zoom on touch screens and Ctrl/Cmd +
   wheel (trackpad pinch) on desktop call `PDFViewer.updateScale` around
   the gesture's centre; the scroll box has `touch-action: pan-x pan-y` so
   the page itself does not zoom. Embedded on a phone the bar keeps pages,
   search and full screen; zoom and download are in full screen.
3. **Full screen is the same element, fixed over the app** (`fixed inset-0`,
   `100dvh`), not the Fullscreen API (unavailable for elements on iOS) and
   not a portal (which would remount the viewer and lose page and zoom).
   Body scroll is locked; Esc closes the search, then full screen; Ctrl/Cmd
   + F opens the PDF search while it is up. Preset zooms (auto, fit width)
   are recomputed when the box changes size.
4. **Run-time files from `/pdfjs/<version>/`.** A small Vite plugin serves
   `wasm/` (JBIG2, JPEG 2000, colour management, with their JavaScript
   fallbacks for a CSP without `wasm-unsafe-eval`), `cmaps/`, `iccs/` and
   `standard_fonts/` from `node_modules/pdfjs-dist` in dev and emits them
   there in the build: whole directories, since pdf.js builds the file
   names itself, and a versioned path so caches never mix releases. They
   sit outside `assets/` and are fetched only by documents that need them.

## Reactivation trigger

- Search inside scans: OCR text is not in the PDF, so the reader's search
  finds nothing on a scan without a text layer. Storing the OCR boxes
  (RapidOCR returns them) and drawing them as an invisible text layer
  would make scans searchable and selectable in the reader too.
- Mobile back button closing full screen: needs the router's history
  handling (a pushed state for the open reader).

## Consequences

- Text in PDFs can be selected, copied and searched; links work; zoom is
  sharp; the reader takes the whole screen on a phone.
- The lazy PDF chunks grow by the viewer module (170 KB) and its style
  sheet (230 KB, 42 KB gzipped); the static output grows by 3.4 MB of
  pdf.js run-time files, fetched only when a document needs them. The
  proxy serving the static volume must serve `.wasm` (as `application/wasm`
  where it streams) and `.bcmap` files.
