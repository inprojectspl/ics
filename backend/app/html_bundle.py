"""HTML bundle guardrails: extension allowlist, entry selection, MIME types, CSP.

Script content is scanned in `app.bundle_scan`; the main guardrail is runtime
isolation (separate origin, iframe `sandbox`, CSP).
"""

from __future__ import annotations

import mimetypes

from app.domain_errors import InvalidInputError

# Anything else is dropped on upload (400 if nothing is left).
ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {
        # Pages
        "html",
        "htm",
        # Styling / scripts
        "css",
        "js",
        "mjs",
        "map",
        # Data / config
        "json",
        "txt",
        "md",
        "csv",
        # Images
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp",
        "svg",
        "ico",
        "avif",
        # Fonts
        "woff",
        "woff2",
        "ttf",
        "otf",
        "eot",
        # Misc media
        "mp4",
        "webm",
        "ogg",
        "mp3",
        "wav",
    }
)


def _render_csp(cdn: str) -> str:
    return (
        "default-src 'self'; "
        f"script-src 'self' 'unsafe-inline'{cdn}; "
        f"style-src 'self' 'unsafe-inline'{cdn}; "
        "img-src 'self' data: blob: https:; "
        f"font-src 'self' data:{cdn}; "
        f"connect-src 'self'{cdn}; "
        "media-src 'self' data: blob: https:; "
        "frame-ancestors 'self'; "
        "base-uri 'none'; "
        "form-action 'none'; "
        "object-src 'none';"
    )


# CSP without trusted CDN hosts. `unsafe-inline` stays because generated pages
# almost always inline script and style; the defence is the separate origin.
BUNDLE_CSP: str = _render_csp("")


# For bundle files served on the app origin (legacy `/static/` links): an
# opaque origin, so scripts still run but carry no ICS session (the session
# cookie is SameSite=Lax and the CSRF check rejects `Origin: null`).
APP_ORIGIN_SANDBOX = " sandbox allow-scripts allow-popups allow-modals allow-downloads;"


def build_csp(trusted_hosts: frozenset[str] | None = None) -> str:
    """`BUNDLE_CSP` with the trusted CDN hosts added to script, style, font and
    connect sources."""
    if not trusted_hosts:
        return BUNDLE_CSP
    return _render_csp(" " + " ".join(sorted(trusted_hosts)))


from app.collections_io import normalize_collection_path as normalize_bundle_path  # noqa: E402,F401


def is_allowed_path(p: str) -> bool:
    ext = p.rsplit(".", 1)[-1].lower() if "." in p else ""
    return ext in ALLOWED_EXTENSIONS


def pick_html_entry(paths: list[str]) -> str:
    """The bundle's entry: shallowest `index.html`, then any `*.html` at
    shallowest depth alphabetically. Raises 400 if no .html file is present."""
    lower = [(p, p.lower()) for p in paths]
    indices = [p for p, lp in lower if lp == "index.html" or lp.endswith("/index.html")]
    if indices:
        indices.sort(key=lambda p: (p.count("/"), p))
        return indices[0]
    htmls = [p for p, lp in lower if lp.endswith(".html") or lp.endswith(".htm")]
    if not htmls:
        raise InvalidInputError(
            "html_entry_missing",
            "an HTML bundle must contain at least one .html file",
        )
    htmls.sort(key=lambda p: (p.count("/"), p))
    return htmls[0]


#: Extensions for which a line diff and partial read make sense. The other
#: allowed types (images, fonts, media) are bytes, so only metadata is shown.
TEXT_EXTENSIONS: frozenset[str] = frozenset(
    {
        "html",
        "htm",
        "css",
        "js",
        "mjs",
        "map",
        "json",
        "txt",
        "md",
        "csv",
        "svg",
    }
)


def is_text_path(p: str) -> bool:
    """Whether the extension suggests text, without reading the file; the verdict
    is `collections_io.decode_text`."""
    ext = p.rsplit(".", 1)[-1].lower() if "." in p else ""
    return ext in TEXT_EXTENSIONS


def binary_file_detail(path: str, size_bytes: int, hint: str) -> dict:
    """Shared `detail` of a 415 on a binary file; clients branch on its `code`."""
    return {
        "code": "binary_file",
        "mime": content_type_for(path),
        "size_bytes": size_bytes,
        "hint": hint,
    }


def content_type_for(path: str) -> str:
    """Content-Type by extension; unknown types are octet-stream so browsers do not
    execute them."""
    guessed, _ = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"


mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("image/avif", ".avif")
mimetypes.add_type("font/woff", ".woff")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("application/manifest+json", ".webmanifest")
# Documents (downloads of pdf_doc / office_doc): slim container images ship
# no /etc/mime.types, so without these they would go out as octet-stream.
mimetypes.add_type(
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"
)
mimetypes.add_type("application/vnd.oasis.opendocument.text", ".odt")
mimetypes.add_type("application/msword", ".doc")
