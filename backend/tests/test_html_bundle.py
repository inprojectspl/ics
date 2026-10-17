"""HTML bundle guardrails: extension allowlist, path normalization,
entry-file selection, MIME type resolution."""

import pytest

from app.domain_errors import DomainError
from app.errors import domain_status
from app.html_bundle import (
    ALLOWED_EXTENSIONS,
    BUNDLE_CSP,
    content_type_for,
    is_allowed_path,
    normalize_bundle_path,
    pick_html_entry,
)

# ---------- extension allowlist ----------


def test_html_allowed():
    assert is_allowed_path("index.html")
    assert is_allowed_path("nested/page.htm")


def test_css_js_allowed():
    assert is_allowed_path("style.css")
    assert is_allowed_path("script.js")
    assert is_allowed_path("module.mjs")


def test_image_formats_allowed():
    for ext in ("png", "jpg", "jpeg", "gif", "webp", "svg", "ico", "avif"):
        assert is_allowed_path(f"img/test.{ext}"), ext


def test_executable_extensions_rejected():
    for bad in ("evil.exe", "shell.sh", "script.bat", "pwn.cmd", "lib.dll", "binary.so"):
        assert not is_allowed_path(bad), bad


def test_no_extension_rejected():
    assert not is_allowed_path("Makefile")
    assert not is_allowed_path(".env")


def test_php_and_jsp_rejected():
    """Server-side templates that could be misinterpreted by reverse proxy."""
    assert not is_allowed_path("page.php")
    assert not is_allowed_path("legacy.jsp")
    assert not is_allowed_path("asp.aspx")


def test_extension_case_insensitive():
    assert is_allowed_path("PAGE.HTML")
    assert is_allowed_path("style.CSS")


# ---------- path normalization ----------


def test_normalize_strips_leading_slash():
    assert normalize_bundle_path("/a/b.html") == "a/b.html"


def test_normalize_collapses_backslash():
    assert normalize_bundle_path("a\\b\\c.html") == "a/b/c.html"


def test_normalize_rejects_traversal():
    with pytest.raises(DomainError) as exc:
        normalize_bundle_path("../escape.html")
    assert domain_status(exc.value) == 400


def test_normalize_rejects_empty():
    with pytest.raises(DomainError):
        normalize_bundle_path("")


# ---------- entry-file selection ----------


def test_pick_entry_prefers_root_index_html():
    paths = ["nested/index.html", "index.html", "style.css"]
    assert pick_html_entry(paths) == "index.html"


def test_pick_entry_prefers_shallowest_index():
    paths = ["a/b/c/index.html", "demo/index.html", "style.css"]
    assert pick_html_entry(paths) == "demo/index.html"


def test_pick_entry_falls_back_to_any_html():
    paths = ["nested/page.html", "style.css"]
    assert pick_html_entry(paths) == "nested/page.html"


def test_pick_entry_rejects_no_html():
    with pytest.raises(DomainError) as exc:
        pick_html_entry(["style.css", "image.png"])
    assert domain_status(exc.value) == 400


# ---------- content type ----------


def test_content_type_html():
    assert content_type_for("page.html").startswith("text/html")


def test_content_type_js():
    ct = content_type_for("script.js")
    assert "javascript" in ct or ct == "application/javascript"


def test_content_type_unknown_falls_back():
    assert content_type_for("file.weirdext") == "application/octet-stream"


def test_content_type_webp_avif_woff2_registered():
    assert content_type_for("img.webp") == "image/webp"
    assert content_type_for("img.avif") == "image/avif"
    assert content_type_for("font.woff2") == "font/woff2"


# ---------- CSP sanity ----------


def test_csp_blocks_cross_origin():
    """default-src 'self' must be present so bundles can't beacon outwards."""
    assert "default-src 'self'" in BUNDLE_CSP
    assert "object-src 'none'" in BUNDLE_CSP
    assert "frame-ancestors 'self'" in BUNDLE_CSP


def test_csp_disallows_form_submission():
    assert "form-action 'none'" in BUNDLE_CSP


def test_allowed_extensions_does_not_contain_active_server_types():
    bad_ext = {"php", "jsp", "aspx", "asp", "py", "rb", "pl", "sh", "exe"}
    assert not (bad_ext & ALLOWED_EXTENSIONS)
