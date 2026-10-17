"""Agent context pack (ADR-0019): ordering of every group, truncation from the
end with required documents kept, inheritance from ancestors, superseded
documents collapsing into their successor, hidden_count only for owners of
the mapped project, and an empty 200 for a task with nothing visible."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

import pytest

from app.models import (
    AssetExternalRef,
    AssetRelation,
    DocType,
    Project,
    ProjectExternalRef,
    ProjectKeyDocument,
    ProjectMember,
)
from app.services import pat
from app.slug import generate_slug
from app.token_estimate import tokens_for_json
from tests.conftest import login_as, mk_admin, mk_asset, mk_user


def _wp() -> str:
    # Fixed width: the pack's `estimated_tokens` counts the task id, so two
    # packs compared whole must not differ in its length.
    return str(10**8 + secrets.randbelow(9 * 10**8))


def _link(asset, wp, *, role="context", required=False, user=None):
    return AssetExternalRef(
        asset_id=asset.id,
        system="openproject",
        entity="work_package",
        external_id=wp,
        role=role,
        required=required,
        origin="manual",
        created_by=user.id if user else None,
    )


def _edge(source, target, relation_type, user):
    return AssetRelation(
        source_asset_id=source.id,
        target_asset_id=target.id,
        relation_type=relation_type,
        target_version=1,
        origin="manual",
        created_by=user.id,
    )


async def _project(session, owner, *, external: str | None = None, members=()):
    project = Project(slug=generate_slug(), name="Pack", created_by=owner.id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectMember(
            project_id=project.id, user_id=owner.id, role="owner", accepted_at=datetime.now(UTC)
        )
    )
    for user, role in members:
        session.add(
            ProjectMember(
                project_id=project.id, user_id=user.id, role=role, accepted_at=datetime.now(UTC)
            )
        )
    if external:
        session.add(
            ProjectExternalRef(project_id=project.id, system="openproject", external_id=external)
        )
    await session.flush()
    return project


async def _pack(client, wp, **params):
    r = await client.get("/api/context", params={"wp": wp, **params})
    assert r.status_code == 200, r.text
    return r.json()


def _slugs(body):
    return [d["slug"] for d in body["documents"]]


async def _all_groups(session):
    """One document per ordering group, created in reverse order so that
    insertion order cannot explain the result."""
    owner = await mk_user(session)
    wp, parent, op_project = _wp(), _wp(), f"op-{generate_slug(8).lower()}"
    names = ["deliverable", "reference", "n_other", "n_derived", "n_depends", "key", "inherited"]
    names += ["direct", "required"]
    docs = {n: await mk_asset(session, owner, title=n) for n in names}
    docs["required"].summary = "Mandatory user story. " * 40
    # Titles are never shortened, so this one alone is over the smallest budget.
    docs["required"].title = "Mandatory user story " * 23
    project = await _project(session, owner, external=op_project)
    for a in docs.values():
        a.project_id = project.id
    session.add_all(
        [
            _link(docs["deliverable"], wp, role="deliverable"),
            _link(docs["reference"], wp, role="reference"),
            _link(docs["inherited"], parent),
            _link(docs["direct"], wp),
            _link(docs["required"], wp, role="reference", required=True),
            ProjectKeyDocument(project_id=project.id, asset_id=docs["key"].id, position=0),
            _edge(docs["direct"], docs["n_other"], "part_of", owner),
            _edge(docs["direct"], docs["n_derived"], "derived_from", owner),
            _edge(docs["direct"], docs["n_depends"], "depends_on", owner),
        ]
    )
    await session.commit()
    # A document linked to the task itself comes before any graph neighbour.
    order = ["required", "direct", "inherited", "key", "reference", "n_depends", "n_derived"]
    order += ["n_other", "deliverable"]
    params = {"ancestors": parent, "project": op_project, "include": "deliverables"}
    return owner, wp, params, [docs[n].slug for n in order]


@pytest.mark.asyncio
async def test_groups_are_ordered_and_truncated_from_the_end(client, session):
    owner, wp, params, expected = await _all_groups(session)
    await login_as(client, owner)

    full = await _pack(client, wp, budget_tokens=4000, **params)
    assert _slugs(full) == expected
    assert full["truncated"] is None
    assert full["project"]["external"] == params["project"]
    required = full["documents"][0]
    assert required["required"] is True
    assert required["via"] == [{"kind": "direct", "role": "reference", "required": True}]
    # Compact entries: no nulls, no derivable or default fields.
    assert len(required["summary"]) <= 200
    for doc in full["documents"]:
        assert {"slug", "title", "version", "via"} <= set(doc)
        assert not {"ref", "doc_type_hint", "content_updated_at", "has_outline"} & set(doc)
        assert "freshness" not in doc and None not in doc.values()
    neighbour = full["documents"][5]
    assert neighbour["via"] == [{"kind": "neighbour", "from": expected[1], "type": "depends_on"}]

    medium = await _pack(client, wp, budget_tokens=450, **params)
    kept = _slugs(medium)
    assert 1 < len(kept) < len(expected)
    assert kept == expected[: len(kept)]
    cut = medium["truncated"]
    assert cut["documents"] + cut["neighbours"] == len(expected) - len(kept)


def _measured(body) -> int:
    """The service's estimate of the response as served."""
    return tokens_for_json(body)


@pytest.mark.asyncio
async def test_whole_response_fits_the_budget_and_says_how_to_get_more(client, session):
    owner, wp, params, expected = await _all_groups(session)
    await login_as(client, owner)

    budget = 450
    body = await _pack(client, wp, budget_tokens=budget, **params)
    # Edges, warnings and the truncation note count too, not just documents.
    assert _measured(body) <= body["estimated_tokens"] <= budget
    assert len(body["documents"]) < len(expected)
    cut = body["truncated"]
    assert cut["max_budget_tokens"] == 4000
    assert budget < cut["needed_tokens"] <= 4000

    # Asking for the size the server reported returns what was left out.
    more = await _pack(client, wp, budget_tokens=cut["needed_tokens"], **params)
    assert _slugs(more) == expected
    assert more["truncated"] is None
    assert _measured(more) <= more["estimated_tokens"] <= cut["needed_tokens"]
    assert len(more["edges"]) == 3


@pytest.mark.asyncio
async def test_required_document_is_never_truncated(client, session):
    owner, wp, params, expected = await _all_groups(session)
    await login_as(client, owner)

    body = await _pack(client, wp, budget_tokens=200, **params)
    # The required document alone is over the budget and still listed.
    assert _slugs(body) == expected[:1]
    assert body["truncated"]["documents"] == 5
    assert body["truncated"]["neighbours"] == 3
    assert body["truncated"]["seed"] == expected[0]
    assert body["estimated_tokens"] > 200


@pytest.mark.asyncio
async def test_epic_documents_are_inherited_nearer_ancestor_first(client, session):
    owner = await mk_user(session)
    wp, story, epic = _wp(), _wp(), _wp()
    epic_doc = await mk_asset(session, owner, title="A epic goals")
    story_doc = await mk_asset(session, owner, title="B story design")
    epic_link = _link(epic_doc, epic)
    epic_link.label, epic_link.note = "Customer portal", "The contract; do not start without it"
    story_link = _link(story_doc, story)
    story_link.note = ""
    session.add_all([epic_link, story_link])
    await session.commit()
    await login_as(client, owner)

    body = await _pack(client, wp, ancestors=f"{story},{epic}")
    assert _slugs(body) == [story_doc.slug, epic_doc.slug]
    assert body["documents"][1]["via"] == [
        {
            "kind": "inherited",
            "wp": epic,
            "role": "context",
            "required": False,
            "label": "Customer portal",
            "note": "The contract; do not start without it",
        }
    ]
    # An empty note or label is left out.
    assert body["documents"][0]["via"] == [
        {"kind": "inherited", "wp": story, "role": "context", "required": False}
    ]
    # Repeated `ancestors` parameters work the same as a comma list.
    r = await client.get(
        "/api/context", params=[("wp", wp), ("ancestors", story), ("ancestors", epic)]
    )
    assert _slugs(r.json()) == [story_doc.slug, epic_doc.slug]


@pytest.mark.asyncio
async def test_superseded_required_document_hands_over_to_successor(client, session):
    owner = await mk_user(session)
    wp = _wp()
    old = await mk_asset(session, owner, title="Spec v1")
    new = await mk_asset(session, owner, title="Spec v2")
    other = await mk_asset(session, owner, title="Notes")
    session.add_all(
        [
            _link(other, wp),
            _link(old, wp, required=True),
            _edge(new, old, "supersedes", owner),
        ]
    )
    await session.commit()
    await login_as(client, owner)

    body = await _pack(client, wp)
    assert _slugs(body) == [new.slug, old.slug, other.slug]
    successor, line = body["documents"][0], body["documents"][1]
    assert successor["required"] is True
    assert {"kind": "successor_of", "slug": old.slug, "required": True} in successor["via"]
    assert line == {
        "slug": old.slug,
        "title": "Spec v1",
        "freshness": "superseded",
        "collapsed": True,
        "superseded_by": new.slug,
        "required": True,
    }
    assert body["warnings"] == [
        {
            "code": "superseded",
            "params": {"slug": old.slug, "successor": new.slug, "required": True},
        }
    ]


@pytest.mark.asyncio
async def test_warnings_are_codes_with_params(client, session):
    owner = await mk_user(session)
    wp = _wp()
    spec = await mk_asset(session, owner, title="A spec")
    notes = await mk_asset(session, owner, title="B notes")
    spec.version = 2
    pinned = _link(spec, wp)
    pinned.pinned_version = 1
    session.add_all([pinned, _link(notes, wp), _edge(spec, notes, "contradicts", owner)])
    await session.commit()
    await login_as(client, owner)

    body = await _pack(client, wp)
    assert body["warnings"] == [
        {"code": "basis_changed", "params": {"slug": spec.slug}},
        {"code": "contradicts", "params": {"from": spec.slug, "to": notes.slug}},
    ]


@pytest.mark.asyncio
async def test_compact_edges_hint_once_per_type_and_content_links_folded(client, session):
    owner = await mk_user(session)
    wp = _wp()
    spec = await mk_asset(session, owner, title="A spec")
    design = await mk_asset(session, owner, title="B design")
    notes = await mk_asset(session, owner, title="C notes")
    for a in (spec, design):
        a.doc_type = "specification"
    notes.version = 3
    link = _edge(design, spec, "references", owner)
    link.origin = "extracted"
    anchored = _edge(spec, notes, "derived_from", owner)
    anchored.target_anchor = "scope"
    session.add_all(
        [
            _link(spec, wp),
            _link(design, wp),
            _link(notes, wp),
            _edge(design, spec, "depends_on", owner),
            link,
            anchored,
        ]
    )
    await session.commit()
    await login_as(client, owner)

    body = await _pack(client, wp)
    hint = (await session.get(DocType, "specification")).agent_hint
    assert body["doc_types"] == ({"specification": hint} if hint else {})
    # The content link repeats the typed edge between the same pair: listed once.
    assert sorted(body["edges"], key=str) == sorted(
        [
            [design.slug, "depends_on", spec.slug],
            [spec.slug, "derived_from", notes.slug, {"target_anchor": "scope", "changed": [1, 3]}],
        ],
        key=str,
    )


@pytest.mark.asyncio
async def test_hidden_count_only_for_owner_of_mapped_project(client, session):
    owner = await mk_user(session)
    member = await mk_user(session)
    stranger = await mk_user(session)
    op_project = f"op-{generate_slug(8).lower()}"
    project = await _project(session, owner, external=op_project, members=[(member, "editor")])
    wp = _wp()
    visible = await mk_asset(session, owner, title="Visible")
    visible.project_id = project.id
    hidden = await mk_asset(session, stranger, title="Hidden")
    session.add_all([_link(visible, wp), _link(hidden, wp)])
    await session.commit()

    await login_as(client, owner)
    body = await _pack(client, wp, project=op_project)
    assert _slugs(body) == [visible.slug]
    # The stranger's document is outside the project, so it is not counted:
    # the owner only learns about the project's own documents.
    assert body["hidden_count"] == 0

    await login_as(client, member)
    body = await _pack(client, wp, project=op_project)
    assert _slugs(body) == [visible.slug]
    assert "hidden_count" not in body


@pytest.mark.asyncio
async def test_owner_of_unrelated_project_cannot_probe_a_foreign_task(client, session):
    victim = await mk_user(session)
    prober = await mk_user(session)
    victim_project = await _project(session, victim)
    own_project = await _project(session, prober)
    wp = _wp()
    secret = await mk_asset(session, victim, title="Secret")
    secret.project_id = victim_project.id
    session.add(_link(secret, wp))
    await session.commit()
    await login_as(client, prober)

    body = await _pack(client, wp, project=own_project.slug)
    empty = await _pack(client, _wp(), project=own_project.slug)
    assert body["documents"] == []
    assert "hidden_count" not in body
    # Both are unlinked for the prober; only the task id differs.
    assert body["warnings"] == [
        {"code": "task_unlinked", "params": {"system": "openproject", "wp": wp}}
    ]
    assert body == {**empty, "task": body["task"], "warnings": body["warnings"]}


@pytest.mark.asyncio
async def test_admin_pat_gets_no_hidden_count(client, session):
    admin = await mk_admin(session)
    owner = await mk_user(session)
    project = await _project(session, owner)
    wp = _wp()
    doc = await mk_asset(session, owner, title="In project")
    doc.project_id = project.id
    session.add(_link(doc, wp))
    await session.commit()
    _, token = await pat.create(
        session, user=admin, name="ps", expires_at=datetime.now(UTC) + timedelta(days=30)
    )
    await session.commit()

    r = await client.get(
        "/api/context",
        params={"wp": wp, "project": project.slug},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    # A PAT has no admin bypass (ADR-0020): no project role, no documents.
    assert r.json()["documents"] == []
    assert "hidden_count" not in r.json()

    await login_as(client, admin)
    body = await _pack(client, wp, project=project.slug)
    assert _slugs(body) == [doc.slug]
    assert body["hidden_count"] == 0


@pytest.mark.asyncio
async def test_hidden_only_task_is_an_empty_200(client, session):
    reader = await mk_user(session)
    stranger = await mk_user(session)
    wp = _wp()
    hidden = await mk_asset(session, stranger, title="Hidden")
    session.add(_link(hidden, wp))
    await session.commit()
    await login_as(client, reader)

    body = await _pack(client, wp, project="not-mapped-anywhere")
    unknown = await _pack(client, _wp())
    assert body["documents"] == [] == unknown["documents"]
    assert "hidden_count" not in body
    assert hidden.slug not in str(body)
    # A hidden link and no link at all look the same.
    assert body["warnings"] == [
        {"code": "project_unmapped", "params": {"project": "not-mapped-anywhere"}},
        {"code": "task_unlinked", "params": {"system": "openproject", "wp": wp}},
    ]
    assert unknown["warnings"] == [
        {"code": "task_unlinked", "params": {"system": "openproject", "wp": unknown["task"]["wp"]}}
    ]


@pytest.mark.asyncio
async def test_unlinked_task_with_key_documents_is_flagged(client, session):
    owner = await mk_user(session)
    wp, op_project = _wp(), f"op-{generate_slug(8).lower()}"
    project = await _project(session, owner, external=op_project)
    key = await mk_asset(session, owner, title="Key")
    linked = await mk_asset(session, owner, title="Linked")
    key.project_id = project.id
    session.add_all(
        [
            ProjectKeyDocument(project_id=project.id, asset_id=key.id, position=0),
            _link(linked, wp),
        ]
    )
    await session.commit()
    await login_as(client, owner)

    # A mistyped work package still gets the key documents, and a warning.
    typo = _wp()
    body = await _pack(client, typo, project=op_project)
    assert _slugs(body) == [key.slug]
    assert body["warnings"] == [
        {"code": "task_unlinked", "params": {"system": "openproject", "wp": typo}}
    ]
    body = await _pack(client, wp, project=op_project)
    assert _slugs(body) == [linked.slug, key.slug]
    assert body["warnings"] == []


@pytest.mark.asyncio
async def test_invalid_work_package_is_rejected(client, session):
    await login_as(client, await mk_user(session))
    r = await client.get("/api/context", params={"wp": "abc"})
    assert r.status_code == 400
    assert r.json()["code"] == "external_ref_invalid"
