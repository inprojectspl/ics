"""A micro-application read as a document: the app's own view of its content
(its document view), what it is, its state, roles and data model, and the
records the reader may list.

Agents read every asset as Markdown; for this kind the content is the app's
data, so the view and the records come from the broker as the reader, with
their permissions and row scopes (the same rules as in the app). Nothing here
bypasses them.
"""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collections_io import MAX_LINES_RANGE, slice_lines
from app.config import Settings
from app.domain_errors import NotFoundError
from app.models import User
from app.render_cache import render_live_text
from app.services.micro_applications import access, catalog, content, status
from app.services.micro_applications.common import ENVIRONMENT, broker_admin, load_app

CELL_MAX = 200


def _cell(value: Any) -> str:
    if value is None:
        return ""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = " ".join(text.split()).replace("|", "\\|")
    return text if len(text) <= CELL_MAX else text[: CELL_MAX - 1] + "…"


def _table(items: list[dict[str, Any]]) -> list[str]:
    columns: list[str] = []
    for item in items:
        columns += [k for k in item if k not in columns]
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    lines += ["| " + " | ".join(_cell(i.get(c)) for c in columns) + " |" for i in items]
    return lines


def _collection_section(entry: dict[str, Any], *, cursor: str | None) -> list[str]:
    name = entry["name"]
    if not entry["readable"]:
        perm = entry.get("permission")
        why = f"needs `{perm}`" if perm else "the app offers no list operation"
        return [f"### {name}", "", f"Not readable for you ({why}).", ""]
    items = entry.get("items") or []
    head = f"### {name}" + (" (continued)" if cursor else "")
    if not items:
        return [head, "", "No records you can see.", ""]
    lines = [head, "", *_table(items), ""]
    if entry.get("next_cursor"):
        lines += [
            f'More records: `ics_asset_read(path="data/{name}", '
            f'cursor="{entry["next_cursor"]}")` '
            f"(API: `?collection={name}&cursor={entry['next_cursor']}`).",
            "",
        ]
    return lines


async def _name_authors(session: AsyncSession, collections: list[dict[str, Any]]) -> None:
    """`created_by` holds an ICS user id or an anonymous link visitor's id;
    show people by name, visitors as such."""
    ids: set[UUID] = set()
    for entry in collections:
        for item in entry.get("items") or []:
            try:
                ids.add(UUID(str(item.get("created_by"))))
            except ValueError:
                continue
    if not ids:
        return
    names = {
        str(u.id): u.display_name or u.email.split("@", 1)[0]
        for u in await session.scalars(select(User).where(User.id.in_(ids)))
    }
    for entry in collections:
        for item in entry.get("items") or []:
            if "created_by" in item:
                item["created_by"] = names.get(str(item["created_by"]), "link visitor")


async def _broker(
    settings: Settings, path: str, body: dict[str, Any]
) -> tuple[dict[str, Any], str | None]:
    """A broker admin call, or (`{}`, error code) when it cannot answer."""
    try:
        return await broker_admin(settings, "POST", path, body), None
    except httpx.HTTPStatusError as e:
        try:
            return {}, str(e.response.json().get("code") or "broker_error")
        except ValueError:
            return {}, "broker_error"
    except httpx.HTTPError:
        return {}, "broker_unavailable"


# A fence opens and closes with the same character, at least as long (CommonMark).
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_HEADING = re.compile(r"^(#{1,6})(\s)")


def _demote(markdown: str) -> list[str]:
    """The app's Markdown under our `## App view`: its headings go two
    levels deeper (at most `######`), code blocks stay as written."""
    out: list[str] = []
    fence: str | None = None
    for line in markdown.splitlines():
        m = _FENCE.match(line)
        if fence is None and m:
            fence = m.group(1)
        elif fence is not None:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
        else:
            line = _HEADING.sub(lambda h: "#" * min(6, len(h.group(1)) + 2) + h.group(2), line)
        out.append(line)
    return out


def _app_view_section(manifest: dict[str, Any], view: dict[str, Any]) -> list[str]:
    """`## App view` from the broker's answer: the app's Markdown, or why
    there is none (`forbidden` names the permission the view needs)."""
    lines = ["## App view", ""]
    if "markdown" in view:
        return [
            *lines,
            "_The app's content as the app renders it for you (records filled in)._",
            "",
            *_demote(view["markdown"]),
            "",
        ]
    needs = (content.document_endpoint(manifest) or {}).get("permission")
    if view.get("error") == "forbidden" and needs:
        return [*lines, f"Not readable for you (needs `{needs}`).", ""]
    return [*lines, f"App view unavailable now (`{view.get('error', 'broker_error')}`).", ""]


def _access_section(release: Any) -> list[str]:
    lines: list[str] = []
    roles = catalog.role_catalog(release)
    if roles:
        lines += [
            "## Roles",
            "",
            "| role | name | permissions | description |",
            "|---|---|---|---|",
        ]
        lines += [
            f"| `{r['role']}` | {_cell(r['label'])} | "
            f"{', '.join(f'`{p}`' for p in r['permissions'])} | {_cell(r['description'])} |"
            for r in roles
        ]
        lines.append("")
    lines += ["## Permissions", ""]
    for item in catalog.permission_catalog(release):
        allows = "; ".join(item["allows"]) or "no operation in this release"
        label = f" ({item['label']})" if item["label"] else ""
        lines.append(f"- `{item['permission']}`{label}: {allows}")
    lines.append("")
    return lines


def _model_section(manifest: dict[str, Any]) -> list[str]:
    lines = ["## Data model", ""]
    for name, collection in (manifest.get("database") or {}).get("collections", {}).items():
        lines += [f"### {name}", "", "| field | type | required |", "|---|---|---|"]
        for field, spec in collection.get("fields", {}).items():
            kind = spec.get("type", "")
            values = spec.get("values") or spec.get("enum")
            if values:
                kind += ": " + ", ".join(map(str, values))
            lines.append(f"| {field} | {kind} | {'yes' if spec.get('required') else ''} |")
        lines.append("")
    return lines


async def render(
    session: AsyncSession,
    settings: Settings,
    user: User,
    asset_id: Any,
    *,
    collection: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    overview: bool = True,
    lines: str | None = None,
    max_lines: int | None = None,
    html: bool = True,
) -> dict[str, Any]:
    """The app first as its own document view renders it (when the release
    declares one), then its roles, model and raw records. `overview=False`
    leaves out what an asset page already shows above the data (title,
    state, permissions); `lines`/`max_lines` slice the Markdown like a file
    read; `html=False` skips the HTML an agent does not use."""
    asset, env = await load_app(session, asset_id)
    rights = await access.rights(session, user, asset)
    if not rights.use:
        raise NotFoundError("not_found", "micro-application not found")
    release = await access.active_release(session, env)
    manifest: dict[str, Any] = release.manifest if release else {}
    whole = collection is None
    has_view = whole and bool(manifest.get("document"))
    # One broker call: the records and the app's view, under one authorization.
    exported, error = (
        await _broker(
            settings,
            f"/admin/apps/{env.asset_hex}/{ENVIRONMENT}/export",
            {
                "user_id": str(user.id),
                "collection": collection,
                "limit": limit,
                "cursor": cursor,
                "document": has_view,
            },
        )
        if release
        else ({}, "app_not_ready")
    )
    if release:
        # Reading the app's data counts as a wake-up for its sheet link
        # (ADR-0032): a sleeping app's sheet is not read otherwise.
        from app.services.sheets import auto

        await auto.enqueue_soon(settings, await auto.read_links(session, settings, asset.id))
    collections: list[dict[str, Any]] = list(exported.get("collections") or [])
    await _name_authors(session, collections)
    app_view = exported.get("document") or {"error": error or "broker_error"}
    out: list[str] = []
    if whole and overview:
        view = await status.detail(session, settings, user, asset_id)
        mine = sorted(access.expand(rights.grants, release))
        my_roles = access.held_roles(rights.grants, release)
        description = (manifest.get("metadata") or {}).get("description")
        runtime = (view.get("runtime") or {}).get("state")
        active = view.get("active_release") or {}
        out += [f"# {asset.title}", ""]
        if description:
            out += [description, ""]
        out += [
            "| | |",
            "|---|---|",
            "| kind | micro-application (`micro_application`) |",
            f"| app | {view.get('app_url')} |",
            f"| state | {view.get('desired_state')}, runtime {runtime} |",
            f"| release | package v{active.get('package_version', '-')} "
            f"(latest package v{view.get('package_version')}) |",
            f"| your roles | {', '.join(f'`{r}`' for r in my_roles) or 'none'} |",
            f"| your permissions | {', '.join(f'`{p}`' for p in mine) or 'none'} |",
            "",
        ]
    if has_view:
        out += _app_view_section(manifest, app_view)
    if whole and overview:
        out += _access_section(release)
    if whole:
        out += [*_model_section(manifest), "## Data", ""]
    if error:
        out += [f"Data unavailable now (`{error}`).", ""]
    for entry in collections:
        out += _collection_section(entry, cursor=cursor)
    markdown = "\n".join(out).rstrip() + "\n"
    result: dict[str, Any] = {
        "asset_id": str(asset.id),
        "slug": asset.slug,
        "version": asset.version,
        "title": asset.title,
        "markdown": markdown,
        "collections": [
            {"name": e["name"], "readable": e["readable"], "next_cursor": e.get("next_cursor")}
            for e in collections
        ],
        "error": error,
        "app_view": (
            {
                "endpoint": manifest["document"]["endpoint"],
                "error": None if "markdown" in app_view else app_view.get("error"),
            }
            if has_view
            else None
        ),
    }
    if lines or max_lines:
        result["markdown"], result["total_lines"], result["returned_range"] = slice_lines(
            markdown, lines or f"1-{max_lines}", max_lines=max_lines or MAX_LINES_RANGE
        )
    if html:
        # Sanitized like every rendered document: cells hold users' input.
        result["html"] = await render_live_text(markdown)
    return result
