"""Document downloads keep their content type without system MIME files
(slim container images have no /etc/mime.types, so docx would otherwise go
out as application/octet-stream)."""

from __future__ import annotations

import importlib
import mimetypes

import pytest

from app import html_bundle


@pytest.fixture
def bare_mimetypes():
    mimetypes.init(files=[])  # built-in table only, like python:*-slim
    importlib.reload(html_bundle)
    yield
    mimetypes.init()
    importlib.reload(html_bundle)


@pytest.mark.parametrize(
    ("name", "mime"),
    [
        ("a.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("a.odt", "application/vnd.oasis.opendocument.text"),
        ("a.doc", "application/msword"),
        ("a.pdf", "application/pdf"),
    ],
)
def test_document_types_without_system_mime_files(bare_mimetypes, name, mime):
    assert html_bundle.content_type_for(name) == mime
