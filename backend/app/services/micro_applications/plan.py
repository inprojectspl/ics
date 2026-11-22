"""Plan and apply: the only way to create or change a micro-application.

A plan validates a complete package, stores its bytes under a digest and
lists the effects (routes, collections, migration). Apply takes the plan id,
that digest, the expected generation and an idempotency key, reserves one
durable operation and hands it to the worker. 202 means accepted, not done.
"""

from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, quota
from app.config import Settings
from app.domain_errors import (
    AccessDeniedError,
    ConflictError,
    InvalidInputError,
    LimitExceededError,
    NotFoundError,
)
from app.models import (
    Asset,
    MicroAppEnvironment,
    MicroAppGrant,
    MicroAppPlan,
    MicroAppRelease,
    ShareLink,
    User,
)
from app.permissions import assert_project_contributor
from app.services.micro_applications import access, changes, ddl, manifest
from app.services.micro_applications.common import (
    ENVIRONMENT,
    broker_admin,
    canonical_hash,
    load_app,
    new_id,
)
from app.services.micro_applications.provisioning import Names
from app.services.upload import one_chunk
from app.storage import storage_from_url

PLAN_TTL = timedelta(hours=1)


class ManifestInvalid(InvalidInputError):
    """422 with every diagnostic; the first one fills code/field/file."""


def decode_files(raw: list[dict[str, Any]]) -> list[tuple[str, bytes]]:
    if not isinstance(raw, list) or not raw:
        raise InvalidInputError(
            "files_required", "send the complete package in files", field="files"
        )
    if len(raw) > manifest.LIMITS["max_files"]:
        raise LimitExceededError(
            "package_too_many_files", f"at most {manifest.LIMITS['max_files']} files", field="files"
        )
    out: list[tuple[str, bytes]] = []
    total = 0
    for i, f in enumerate(raw):
        path = f.get("path")
        if not isinstance(path, str):
            raise InvalidInputError(
                "path_invalid", "every file needs a path", field=f"files/{i}/path"
            )
        has_text, has_b64 = "content_text" in f, "content_base64" in f
        if has_text == has_b64:
            raise InvalidInputError(
                "content_required",
                "give exactly one of content_text or content_base64",
                field=f"files/{i}",
            )
        if has_text:
            data = str(f["content_text"]).encode("utf-8")
        else:
            try:
                data = base64.b64decode(str(f["content_base64"]), validate=True)
            except (binascii.Error, ValueError):
                raise InvalidInputError(
                    "base64_invalid", "content_base64 is not valid base64", field=f"files/{i}"
                ) from None
        total += len(data)
        if total > manifest.LIMITS["max_package_bytes"]:
            raise LimitExceededError(
                "package_too_large",
                f"at most {manifest.LIMITS['max_package_bytes']} bytes",
                field="files",
            )
        out.append((path, data))
    return out


def _raise_invalid(diags: list[manifest.Diagnostic]) -> None:
    errors = [d for d in diags if d.severity == "error"]
    first = errors[0]
    raise ManifestInvalid(
        "manifest_invalid",
        first.message,
        field=first.pointer or "/",
        extra={
            "file": first.file,
            "retryable": False,
            "diagnostics": [d.as_dict() for d in diags[:100]],
        },
    )


async def _compile(settings: Settings, pkg: manifest.Package) -> list[manifest.Diagnostic]:
    """Handler syntax, seed rows and the values the manifest states for
    fields (defaults, conditions, allowed values), all checked by the broker:
    the same value rules as a write through the app's API."""
    files = {p: b.decode("utf-8") for p, b in pkg.files.items() if p.startswith("handlers/")}
    assert pkg.manifest is not None
    collections = pkg.manifest["database"]["collections"]
    seeds = {
        f"seed/{c}.json": {"fields": collections[c]["fields"], "rows": rows}
        for c, rows in pkg.seeds.items()
    }
    # Each field once, by pointer; the values name it.
    fields = {v["field"]: _at(pkg.manifest, v["field"]) for v in pkg.values}
    if not files and not seeds and not pkg.values:
        return []
    try:
        result = await broker_admin(
            settings,
            "POST",
            "/admin/compile",
            {"files": files, "seeds": seeds, "values": pkg.values, "fields": fields},
        )
    except Exception as e:
        raise ConflictError(
            "runtime_unavailable",
            "the micro-application runtime could not check the handlers; retry",
            extra={"retryable": True},
        ) from e
    out = []
    for path, r in result.get("results", {}).items():
        if not r.get("ok"):
            out.append(
                manifest.Diagnostic(
                    r.get("code", "syntax_error"), str(r.get("message", ""))[:300], file=path
                )
            )
    out.extend(
        manifest.Diagnostic(p["code"], str(p["message"])[:300], pointer=p["pointer"])
        for p in result.get("values") or []
    )
    for path, problems in (result.get("seeds") or {}).items():
        out.extend(
            manifest.Diagnostic(
                "seed_value_invalid", str(p["message"])[:300], file=path, pointer=p["pointer"]
            )
            for p in problems
        )
    return out


def _at(document: dict[str, Any], pointer: str) -> Any:
    """The value at a JSON Pointer the manifest checks produced (no escapes:
    collection and field names are plain identifiers)."""
    node: Any = document
    for part in pointer.strip("/").split("/"):
        node = node[part]
    return node


def _schema_plan(
    m: dict[str, Any], env: MicroAppEnvironment | None, active: MicroAppRelease | None, schema: str
) -> dict[str, Any]:
    old = env.applied_model if env else {}
    current = env.schema_version if env else 0
    delta = ddl.diff(schema, old, manifest.data_model(m))
    comp = m["compatibility"]
    target = current + 1 if delta.changes_schema else current
    problems: list[dict[str, str]] = list(delta.destructive)
    if not comp["schemaMin"] <= max(target, 1) <= comp["schemaMax"]:
        problems.append(
            {
                "pointer": "/compatibility",
                "reason": f"the release must support schema version {max(target, 1)}",
            }
        )
    if delta.changes_schema and active is not None and active.schema_max < target:
        problems.append(
            {
                "pointer": "/compatibility",
                "reason": (
                    f"the active release supports schema <= {active.schema_max}; publish a "
                    f"transitional release with schemaMax >= {target} first"
                ),
            }
        )
    return {
        "schema_version_from": current,
        "schema_version_to": max(target, 1) if not env else target,
        "destructive": bool(delta.destructive),
        "changes": delta.as_dict(),
        "problems": problems,
    }


async def _orphaned_grants(session: AsyncSession, asset: Asset, m: dict[str, Any]) -> list[str]:
    """Roles and permissions held by people, projects or live links that the
    new manifest no longer defines."""
    held = set(
        await session.scalars(
            select(MicroAppGrant.permission).where(MicroAppGrant.asset_id == asset.id).distinct()
        )
    )
    for link in await session.scalars(
        select(ShareLink.app_permissions).where(
            ShareLink.asset_id == asset.id,
            ShareLink.revoked_at.is_(None),
            or_(ShareLink.expires_at.is_(None), ShareLink.expires_at > func.now()),
        )
    ):
        held.update(link or ())
    valid = (
        set(m["permissions"])
        | set(access.PLATFORM_GRANTS)
        | {access.role_grant(r) for r in m["roles"]}
    )
    return sorted(held - valid)


async def _assert_fits_quota(
    session: AsyncSession, pkg: manifest.Package, asset: Asset | None, user: User
) -> None:
    """The package counts against its owner's storage quota, as every
    upload does; checked here so a plan that cannot be stored is refused
    before anything runs (the publication checks again)."""
    owner = await session.get(User, asset.owner_id) if asset else user
    current = (asset.size_bytes or 0) if asset else 0
    growth = pkg.total_bytes - current
    if owner is not None and growth > 0:
        await quota.assert_can_grow(
            session,
            owner.id,
            incoming_bytes=growth,
            quota_bytes=owner.storage_quota_bytes,
            lock=False,
        )


async def create_plan(
    session: AsyncSession,
    settings: Settings,
    user: User,
    *,
    files: list[dict[str, Any]],
    asset_id: UUID | None,
    project_id: UUID | None,
    change_note: str | None = None,
) -> dict[str, Any]:
    if not access.is_active_internal(user):
        raise AccessDeniedError("forbidden", "an active internal account is required")
    raw = decode_files(files)
    pkg = manifest.load_package(raw)
    if pkg.ok:
        pkg.diagnostics.extend(await _compile(settings, pkg))
    if not pkg.ok:
        _raise_invalid(pkg.diagnostics)
    assert pkg.manifest is not None
    m = pkg.manifest

    env: MicroAppEnvironment | None = None
    active: MicroAppRelease | None = None
    asset: Asset | None = None
    if asset_id is not None:
        asset, env = await load_app(session, asset_id)
        r = await access.rights(session, user, asset)
        if not r.use:
            raise NotFoundError("not_found", "micro-application not found")
        if not r.prepare:
            raise AccessDeniedError("forbidden", "editor rights are needed to prepare a release")
        if env.active_release_id:
            active = await session.get(MicroAppRelease, env.active_release_id)
        action = "update"
        expected = env.control_generation
        schema = Names.for_asset(env.asset_hex, ENVIRONMENT).schema
        permissions_required = ["asset.edit", "app.publish"]
    else:
        if project_id is not None:
            await assert_project_contributor(session, user, project_id)
        action = "create"
        expected = 0
        schema = "a_" + "0" * 32
        permissions_required = ["asset.create", "app.publish"]

    await _assert_fits_quota(session, pkg, asset, user)
    schema_plan = _schema_plan(m, env, active, schema)
    if asset is not None:
        for grant in await _orphaned_grants(session, asset, m):
            pkg.warn(
                "grant_orphaned",
                f"{grant} is given to people or links but this release does not define it; "
                "they lose it on apply (keep it, or change their access)",
                pointer="/roles" if grant.startswith(access.ROLE_PREFIX) else "/permissions",
            )
    if schema_plan["problems"]:
        first = schema_plan["problems"][0]
        raise ManifestInvalid(
            "destructive_change" if schema_plan["destructive"] else "schema_incompatible",
            first["reason"],
            field=first["pointer"],
            extra={
                "file": manifest.MANIFEST_PATH,
                "retryable": False,
                "diagnostics": schema_plan["problems"],
            },
        )

    entries = pkg.file_entries()
    digest = "sha256:" + canonical_hash(
        {
            "files": [(e["path"], e["sha256"]) for e in entries],
            "validator": manifest.VALIDATOR_VERSION,
            "contract": manifest.CONTRACT_VERSION,
            "limits": manifest.LIMITS,
            "target": str(asset_id) if asset_id else None,
            "expected_generation": expected,
        }
    )
    plan_id = new_id("plan")
    prefix = f"microapp-plans/{plan_id}"
    storage = storage_from_url(settings.storage_url)
    for path, data in pkg.files.items():
        await storage.put(f"{prefix}/{path}", one_chunk(data))
    expires = datetime.now(UTC) + PLAN_TTL
    migration = {k: v for k, v in schema_plan.items() if k not in ("problems",)}
    # Seed rows go in only with the collections this release creates.
    added = migration["changes"].get("collections_added", [])
    # Only counts: the rows stay in the package (seed/<collection>.json),
    # which the publication reads from the committed package version.
    migration["seed_rows"] = {c: len(rows) for c, rows in pkg.seeds.items() if c in added}
    seed_ignored = sorted(set(pkg.seeds) - set(migration["seed_rows"]))
    for c in seed_ignored:
        pkg.warn(
            "seed_not_applied",
            f"{c} already exists: seed rows fill a collection only when a release creates it",
            file=f"seed/{c}.json",
        )
    plan = MicroAppPlan(
        id=plan_id,
        user_id=user.id,
        action=action,
        asset_id=asset.id if asset else None,
        project_id=project_id if action == "create" else None,
        digest=digest,
        storage_prefix=prefix,
        files=entries,
        manifest=m,
        contract_version=manifest.CONTRACT_VERSION,
        expected_generation=expected,
        migration=migration,
        diagnostics={"warnings": [d.as_dict() for d in pkg.diagnostics]},
        change_note=(change_note or "").strip() or None,
        expires_at=expires,
    )
    session.add(plan)
    await audit.record(
        session,
        actor=user,
        action="microapp_planned",
        target=f"asset:{asset.id}" if asset else None,
        payload={"plan_id": plan_id, "digest": digest, "action": action},
    )
    await session.commit()
    rights = await access.rights(session, user, asset) if asset else None
    return {
        "plan_id": plan_id,
        "action": action,
        "asset_id": str(asset.id) if asset else None,
        "release_digest": digest,
        "contract_version": manifest.CONTRACT_VERSION,
        "profile": manifest.PROFILE,
        "files": entries,
        # What the release changes for the people using the app (for a new
        # app: everything it brings), the same as a version comparison says.
        "app_changes": changes.manifest_changes(active.manifest if active else {}, m),
        "database": {
            "schema_version_from": migration["schema_version_from"],
            "schema_version_to": migration["schema_version_to"],
            "destructive": False,
            "changes": migration["changes"],
            "seed_rows": migration["seed_rows"],
            "seed_ignored": seed_ignored,
        },
        "document_view": (m.get("document") or {}).get("endpoint"),
        "roles": sorted(m["roles"]),
        "permissions": sorted(m["permissions"]),
        "permissions_required": permissions_required,
        "can_apply": rights.publish if rights else True,
        "effective_limits": {
            "wallMs": min(m["limitsRequested"]["wallMs"], manifest.LIMITS["wall_ms"]),
            "maxDbCalls": min(m["limitsRequested"]["maxDbCalls"], manifest.LIMITS["max_db_calls"]),
            "maxResponseBytes": min(
                m["limitsRequested"]["maxResponseBytes"], manifest.LIMITS["max_response_bytes"]
            ),
            "jsCpuMs": manifest.LIMITS["js_cpu_ms"],
            "guestHeapBytes": manifest.LIMITS["guest_heap_bytes"],
        },
        "expected_generation": expected,
        "expires_at": expires.isoformat(),
        "validation": {
            "status": "passed",
            "warnings": [d.as_dict() for d in pkg.diagnostics],
            "handlers_compiled": sorted(p for p in pkg.files if p.startswith("handlers/")),
            "preview": "not_run",
        },
    }
