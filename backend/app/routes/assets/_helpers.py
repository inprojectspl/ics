"""Helpers used by several `routes.assets` modules or exported outside the
package (`routes.shares`, `routes.html_viewer`, tests)."""

from __future__ import annotations

import asyncio
import io
import re
import zipfile
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Literal

from fastapi import Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app import cdn_allowlist
from app.bundle_scan import localize_report
from app.collections_io import (
    list_version_files,
    md_paths,
    normalize_collection_path,
    read_bytes_at_version,
)
from app.config import Settings
from app.errors import ApiError
from app.html_bundle import (
    build_csp,
    content_type_for,
    is_allowed_path,
    normalize_bundle_path,
)
from app.i18n import DEFAULT_LOCALE, Locale
from app.models import Asset
from app.render_cache import render_asset_file, render_document
from app.routes._version_param import resolve_version_or_404, version_echo
from app.services import asset_security, documents, ocr
from app.services.version_banner import inject_banner
from app.services.versions import entry_from_paths, version_created_at
from app.storage import storage_from_url

# Share modes chosen directly at upload time. Magic-email and password
# shares stay in a separate dialog (they need extra fields), so they are
# not listed here.
UploadShareMode = Literal["org_sso", "public"]


# Characters replaced in the source download file name.
_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def assert_bundle_renderable_for_visitors(asset: Asset) -> None:
    """Critical bundles need an admin bypass before any visitor-facing
    surface (shares, iso-viewer) renders them; owner paths skip this. 410,
    not 403/404: the resource exists but is withheld pending review."""
    if asset_security.publication_blocked(asset):
        raise ApiError(
            status.HTTP_410_GONE,
            "bundle_withheld",
            "bundle withheld: status critical, awaiting administrator approval",
        )


def is_html_doc(rel_path: str) -> bool:
    """Whether the path is an HTML document, not a bundle subresource. Drives
    `no-store` vs cache, the ETag and the prelude; routes check it before
    building a prelude so subresources skip the version-date query."""
    return rel_path.lower().endswith((".html", ".htm"))


def _static_headers(
    csp: str,
    *,
    rel_path: str = "",
    etag: str | None = None,
) -> dict[str, str]:
    """Security headers for every served bundle file.

    `Vary: Cookie` is critical: the viewer gates on the `ics_html_access`
    cookie, so a shared proxy must not serve one user's response to another.
    HTML is `no-store` because its gate (`security_bypass`) can change at any
    time; other files get `private, max-age=3600` plus a version ETag.
    """
    is_html_entry = is_html_doc(rel_path)
    cache = "no-store" if is_html_entry else "private, max-age=3600"
    headers = {
        "Content-Security-Policy": csp,
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": cache,
        "Vary": "Cookie",
    }
    if etag and not is_html_entry:
        headers["ETag"] = etag
    return headers


def _single_file_type(asset: Asset) -> tuple[str, str] | None:
    """`(media type, extension)` of a kind downloaded as its one stored file
    rather than a ZIP; the download name keeps the file's extension."""
    if asset.kind == "md_single":
        return "text/markdown; charset=utf-8", ".md"
    if documents.is_document(asset.kind):
        entry = asset.entry_path or ""
        return content_type_for(entry), PurePosixPath(entry).suffix.lower()
    return None


async def _stream_source(asset: Asset, settings: Settings) -> StreamingResponse:
    """Download response: the one stored file for `md_single` and documents,
    otherwise an in-memory ZIP of the current version (bounded by
    `max_asset_bytes`, and it gives a real `Content-Length`). The caller
    has already authorized access."""
    storage = storage_from_url(settings.storage_url)
    base_name = _FILENAME_SAFE.sub("-", (asset.slug or "ics-asset")).strip("-") or "ics-asset"

    if single := _single_file_type(asset):
        media_type, ext = single
        key = f"{asset.storage_prefix}/v{asset.version}/{asset.entry_path}"
        try:
            stream = await storage.get(key)
        except FileNotFoundError:
            raise ApiError(
                status.HTTP_404_NOT_FOUND, "source_missing", "source file is missing"
            ) from None
        return StreamingResponse(
            stream,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{base_name}{ext}"',
                "Cache-Control": "private, no-store",
            },
        )

    files = await list_version_files(asset, asset.version, settings)
    if not files:
        raise ApiError(status.HTTP_404_NOT_FOUND, "source_missing", "source files are missing")

    # Parallel fetch behind a semaphore (the S3 backend tolerates 8-16
    # concurrent GETs). Zipfile is not thread-safe, so gather covers only
    # the fetch stage; writestr then runs sequentially on the results.
    sem = asyncio.Semaphore(8)

    async def _fetch(rel: str) -> tuple[str, bytes | None]:
        key = f"{asset.storage_prefix}/v{asset.version}/{rel}"
        async with sem:
            try:
                stream = await storage.get(key)
            except FileNotFoundError:
                return rel, None
            chunks = bytearray()
            async for c in stream:
                chunks.extend(c)
        return rel, bytes(chunks)

    fetched = await asyncio.gather(*(_fetch(rel) for rel in files))
    # Deflating a large bundle costs seconds of CPU, so it runs off the
    # event loop; already-compressed members are stored verbatim.
    payload = await asyncio.to_thread(_zip_bytes, fetched)
    return StreamingResponse(
        iter([payload]),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{base_name}.zip"',
            "Content-Length": str(len(payload)),
            "Cache-Control": "private, no-store",
        },
    )


# Media that is already compressed; re-deflating it burns CPU for ~0 gain.
_STORED_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".avif",
        ".ico",
        ".woff",
        ".woff2",
        ".zip",
        ".gz",
        ".mp4",
        ".webm",
        ".mp3",
        ".ogg",
        ".pdf",
    }
)


def _zip_bytes(entries: Sequence[tuple[str, bytes | None]]) -> bytes:
    """Build the archive in one pass. Blocking: call via `to_thread`."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for rel, data in entries:
            if data is None:
                continue
            suffix = rel[rel.rfind(".") :].lower() if "." in rel else ""
            if suffix in _STORED_SUFFIXES:
                zf.writestr(rel, data, compress_type=zipfile.ZIP_STORED)
            else:
                zf.writestr(rel, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
    return buf.getvalue()


async def serve_bundle_file(
    asset: Asset,
    rel_path: str,
    settings: Settings,
    session: AsyncSession | None = None,
    request: Request | None = None,
    *,
    version: int | None = None,
    body_prelude: str | None = None,
) -> Response:
    """Stream one html_bundle file with strict security headers. The caller
    has already authorized access.

    Without `session` only the env CDN allowlist applies, so HTTP handlers
    should pass it. `request` enables the 304 on If-None-Match. `version`
    serves an archived tree. `body_prelude` (ASCII HTML) is injected into
    HTML documents only, which are then buffered; everything else streams.
    """
    if asset.kind != "html_bundle":
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "not_html_bundle", "the document is not an HTML bundle"
        )
    rel = normalize_bundle_path(rel_path)
    if not is_allowed_path(rel):
        raise ApiError(status.HTTP_404_NOT_FOUND, "file_not_found", "file not found")

    v = resolve_version_or_404(asset, version)
    is_html = is_html_doc(rel)
    etag = f'W/"v{v}"'
    if session is not None:
        hosts = await cdn_allowlist.trusted_hosts(session, settings)
    else:
        hosts = settings.trusted_cdn_hosts_set
    headers = _static_headers(build_csp(hosts), rel_path=rel, etag=etag)

    # 304 short-circuit for non-HTML only: the HTML entry is `no-store` and
    # gets no ETag, so it is never revalidated.
    if request is not None and request.headers.get("if-none-match") == etag and not is_html:
        return Response(status_code=304, headers=headers)

    media_type = content_type_for(rel)
    if body_prelude and is_html:
        try:
            raw = await read_bytes_at_version(asset, v, rel, settings)
        except FileNotFoundError:
            raise ApiError(status.HTTP_404_NOT_FOUND, "file_not_found", "file not found") from None
        payload = inject_banner(raw, body_prelude)
        return Response(
            content=payload,
            media_type=media_type,
            headers={**headers, "Content-Length": str(len(payload))},
        )

    storage = storage_from_url(settings.storage_url)
    try:
        stream = await storage.get(f"{asset.storage_prefix}/v{v}/{rel}")
    except FileNotFoundError:
        raise ApiError(status.HTTP_404_NOT_FOUND, "file_not_found", "file not found") from None

    return StreamingResponse(
        stream,
        media_type=media_type,
        headers=headers,
    )


async def render_collection_file(
    asset: Asset, path: str, version: int | None, settings: Settings
) -> dict:
    """Rendered file of a Markdown collection, for `/file` on assets and shares."""
    if asset.kind != "md_collection":
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "collection_only",
            "operation available only for Markdown collections",
        )
    rel = normalize_collection_path(path)
    v = resolve_version_or_404(asset, version)
    try:
        html = await render_asset_file(asset, v, rel, settings)
    except FileNotFoundError:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "file_not_found",
            f"file {rel} does not exist in version v{v}",
        ) from None
    return {
        "slug": asset.slug,
        "path": rel,
        "html": html,
        **version_echo(asset, v),
    }


async def _load_asset_html(asset: Asset, settings: Settings) -> str:
    """Render the entry .md of an md_single / md_collection asset to HTML."""
    if asset.kind not in ("md_single", "md_collection"):
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "kind_not_renderable", "asset kind not renderable here"
        )
    return await render_asset_file(asset, asset.version, entry_or_404(asset), settings)


def entry_or_404(asset: Asset) -> str:
    """The current entry file; a Markdown asset without one is a broken row."""
    if asset.entry_path is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "entry_missing", "the asset has no entry file")
    return asset.entry_path


async def _doc_payload_for(
    asset: Asset,
    settings: Settings,
    *,
    session: AsyncSession | None = None,
    include_security_report: bool = False,
    version: int | None = None,
    locale: Locale = DEFAULT_LOCALE,
) -> dict:
    """JSON payload the viewer consumes for any asset kind.

    `include_security_report` is fail-closed: finding details are a review
    tool for editors, never for share visitors; `security_status` is always
    sent (a visitor learns it from the 410 anyway). `version` is the raw
    `?version=` for a read-only archived preview; `session` adds its date.
    """
    v = resolve_version_or_404(asset, version)
    stale = v != asset.version
    # Query the version date only for archived versions: on the current one
    # (>99% of traffic) no banner is drawn, so the query would be wasted.
    created = await version_created_at(session, asset, v) if stale and session else None
    preview = {
        # `None` for the current version: the frontend uses this to decide
        # whether to draw the "outdated version" banner.
        "preview_version": v if stale else None,
        "current_version": asset.version,
        "version_created_at": created.isoformat() if created else None,
    }

    html_out: str | None = None
    if stale:
        # The archived entry comes from this version's file list (cold path).
        files = await list_version_files(asset, v, settings)
        entry = entry_from_paths(asset, v, files)
        if entry is None:
            raise ApiError(status.HTTP_404_NOT_FOUND, "version_empty", f"version v{v} has no files")
    elif asset.kind == "md_collection":
        # The entry is known from the row, so listing and rendering overlap.
        entry = entry_or_404(asset)
        files, html_out = await asyncio.gather(
            list_version_files(asset, v, settings),
            render_asset_file(asset, v, entry, settings),
        )
    elif asset.kind == "html_bundle":
        entry, files = asset.entry_path, await list_version_files(asset, v, settings)
    else:
        # One file: skip the storage LIST (billed above GET on S3).
        entry, files = asset.entry_path, []

    if asset.kind == "html_bundle" or documents.is_document(asset.kind):
        # Paths only; sizes are served to MCP clients by `files-mcp`. A PDF is
        # rendered from `/pdf`, an Office document as converted `html`.
        counts: dict = {}
        if documents.is_document(asset.kind):
            doc_type = documents.document_type(asset.kind)
            meta = await documents.load_meta(asset, v, settings)
            counts = {doc_type.payload_key: doc_type.summary(meta)}
            block = await ocr.ocr_block(session, asset, v, settings, meta=meta) if session else None
            if block is not None:
                counts["ocr"] = block
            if doc_type.inline_html:
                html_out = await render_document(asset, v, settings)
        return {
            "id": str(asset.id),
            "slug": asset.slug,
            "title": asset.title,
            "kind": asset.kind,
            "version": v,
            "size_bytes": asset.size_bytes,
            "entry_path": entry,
            "html": html_out,
            "tree": None,
            "files": files,
            **counts,
            "security_status": asset.security_status,
            "security_report": (
                localize_report(asset.security_report, locale) if include_security_report else None
            ),
            "security_bypass": asset.security_bypass,
            "created_at": asset.created_at.isoformat(),
            "updated_at": asset.updated_at.isoformat(),
            **preview,
        }

    if html_out is None:
        html_out = await render_asset_file(asset, v, entry or entry_or_404(asset), settings)
    # `list_version_files` already returns sorted paths, so filtering is enough.
    tree = md_paths(files) if asset.kind == "md_collection" else None
    return {
        "id": str(asset.id),
        "slug": asset.slug,
        "title": asset.title,
        "kind": asset.kind,
        "version": v,
        "size_bytes": asset.size_bytes,
        "entry_path": entry,
        "html": html_out,
        "tree": tree,
        "security_status": asset.security_status,
        # Markdown carries only advisory findings (prompt-injection rule).
        "security_report": (
            localize_report(asset.security_report, locale) if include_security_report else None
        ),
        "created_at": asset.created_at.isoformat(),
        "updated_at": asset.updated_at.isoformat(),
        **preview,
    }
