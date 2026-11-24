"""sheet links per spreadsheet file, with mappings of collections to tabs

Revision ID: 0056
Revises: 0055
Create Date: 2026-11-24

A link joins an app to a whole spreadsheet file; what it links moves to
`sheet_mappings`, one per collection, each with one tab or a group of tabs
(ADR-0033). Every existing link becomes one single-tab mapping and keeps
its agreed values and history. The tab's Google id is taken from the
link's latest operation made under its current revision; without one the
first sync pins it by the tab's name. Unapplied previews are superseded;
an operation still applying or writing to Google is rewritten to the new
shape, so it resumes or is checked as before.
"""

import json
import uuid
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0056"
down_revision: str | None = "0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _preview(p: dict[str, Any], mid: str, collection: str) -> dict[str, Any]:
    sheet = p.get("sheet") or {}
    cols = sheet.get("cols") or {}
    part = {
        **{k: v for k, v in p.items() if k not in ("sheet", "release")},
        "collection": collection,
        "sheet": {
            "cols": {f: i for i, f in enumerate(cols)},
            "tabs": [
                {
                    "sheet_id": sheet.get("sheet_id"),
                    "title": sheet.get("title"),
                    "first": 0,
                    "cols": cols,
                }
            ],
        },
    }
    return {
        "release": p.get("release"),
        "summary": p.get("summary") or {},
        "mappings": {mid: part},
    }


def _export(e: dict[str, Any], p: dict[str, Any], mid: str, collection: str) -> dict[str, Any]:
    sheet_id = (p.get("sheet") or {}).get("sheet_id")
    out: dict[str, Any] = {
        "patches": [{**c, "collection": collection} for c in e.get("patches") or []],
        "mappings": {
            mid: {
                "local_base": e.get("local_base") or {},
                "remote_base": e.get("remote_base") or {},
                "rows": {rid: [sheet_id, row] for rid, row in (e.get("rows") or {}).items()},
            }
        },
        "created": e.get("created") or {},
    }
    if "cells" in e:
        out["cells"] = {
            mid: [[sheet_id, c["row"], c["col"], c["field"], c["value"]] for c in e["cells"]]
        }
        out["remote_rows"] = {
            mid: {rid: [sheet_id, row] for rid, row in (e.get("remote_rows") or {}).items()}
        }
    return out


def upgrade() -> None:
    op.create_table(
        "sheet_mappings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "link_id",
            sa.Uuid(),
            sa.ForeignKey("sheet_links.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("collection", sa.String(64), nullable=False),
        sa.Column("tabs", JSONB(), nullable=False),
        sa.Column("key_field", sa.String(64)),
        sa.Column("tab_field", sa.String(64)),
        sa.Column("columns", JSONB(), nullable=False),
        sa.UniqueConstraint("link_id", "collection"),
    )
    op.add_column("sheet_base", sa.Column("mapping_id", sa.Uuid()))
    op.add_column("sheet_base", sa.Column("sheet_id", sa.Integer()))

    conn = op.get_bind()
    links = conn.execute(
        sa.text("SELECT id, collection, sheet_title, key_field, columns, revision FROM sheet_links")
    ).mappings()
    for link in list(links):
        mid = uuid.uuid4()
        latest = (
            conn.execute(
                sa.text(
                    "SELECT preview->'sheet' FROM sheet_operations "
                    "WHERE link_id = :l AND link_revision = :r AND preview ? 'sheet' "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"l": link["id"], "r": link["revision"]},
            ).scalar()
            or {}
        )
        # Only a tab seen under this very mapping vouches for its id.
        sheet_id = latest.get("sheet_id") if latest.get("title") == link["sheet_title"] else None
        conn.execute(
            sa.text(
                "INSERT INTO sheet_mappings (id, link_id, position, collection, tabs, key_field,"
                " columns) VALUES (:id, :l, 0, :c, CAST(:t AS jsonb), :k, CAST(:cols AS jsonb))"
            ),
            {
                "id": mid,
                "l": link["id"],
                "c": link["collection"],
                "t": json.dumps([{"sheet_id": sheet_id, "title": link["sheet_title"]}]),
                "k": link["key_field"],
                "cols": json.dumps(link["columns"]),
            },
        )
        conn.execute(
            sa.text("UPDATE sheet_base SET mapping_id = :m, sheet_id = :s WHERE link_id = :l"),
            {"m": mid, "s": sheet_id, "l": link["id"]},
        )
        conn.execute(
            sa.text(
                "UPDATE sheet_operations SET state = 'superseded', preview = '{}'::jsonb "
                "WHERE link_id = :l AND state = 'previewed'"
            ),
            {"l": link["id"]},
        )
        ops = conn.execute(
            sa.text(
                "SELECT id, state, google_status, preview, export FROM sheet_operations "
                "WHERE link_id = :l AND preview ? 'sheet'"
            ),
            {"l": link["id"]},
        ).mappings()
        for o in list(ops):
            unsettled = o["state"] == "applying" or (
                o["state"] == "applied" and o["google_status"] in ("pending", "uncertain")
            )
            if unsettled:
                preview = _preview(o["preview"], str(mid), link["collection"])
                export = _export(o["export"] or {}, o["preview"], str(mid), link["collection"])
            else:
                # Settled: the history keeps its counts in `summary` only.
                preview, export = {}, None
            conn.execute(
                sa.text(
                    "UPDATE sheet_operations SET preview = CAST(:p AS jsonb), "
                    "export = CAST(:e AS jsonb) WHERE id = :id"
                ),
                {
                    "id": o["id"],
                    "p": json.dumps(preview),
                    "e": json.dumps(export) if export is not None else None,
                },
            )

    op.drop_constraint("sheet_base_pkey", "sheet_base", type_="primary")
    op.drop_column("sheet_base", "link_id")
    op.alter_column("sheet_base", "mapping_id", nullable=False)
    op.create_primary_key("sheet_base_pkey", "sheet_base", ["mapping_id", "record_id"])
    op.create_foreign_key(
        "sheet_base_mapping_id_fkey",
        "sheet_base",
        "sheet_mappings",
        ["mapping_id"],
        ["id"],
        ondelete="CASCADE",
    )
    for name in ("collection", "sheet_title", "key_field", "columns"):
        op.drop_column("sheet_links", name)


def downgrade() -> None:
    # A file with several mappings has no single-tab shape: only the first
    # mapping of each link survives a downgrade, with its agreed values.
    op.add_column("sheet_links", sa.Column("collection", sa.String(64)))
    op.add_column("sheet_links", sa.Column("sheet_title", sa.String(100)))
    op.add_column("sheet_links", sa.Column("key_field", sa.String(64)))
    op.add_column("sheet_links", sa.Column("columns", JSONB()))
    op.add_column("sheet_base", sa.Column("link_id", sa.Uuid()))
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE sheet_links l SET collection = m.collection, "
            "sheet_title = m.tabs->0->>'title', key_field = m.key_field, columns = m.columns "
            "FROM (SELECT DISTINCT ON (link_id) * FROM sheet_mappings "
            "ORDER BY link_id, position) m WHERE m.link_id = l.id"
        )
    )
    conn.execute(sa.text("DELETE FROM sheet_links WHERE collection IS NULL"))
    conn.execute(
        sa.text(
            "UPDATE sheet_base b SET link_id = m.link_id FROM sheet_mappings m "
            "JOIN sheet_links l ON l.id = m.link_id AND l.collection = m.collection "
            "WHERE b.mapping_id = m.id"
        )
    )
    conn.execute(sa.text("DELETE FROM sheet_base WHERE link_id IS NULL"))
    conn.execute(
        sa.text("UPDATE sheet_operations SET state = 'superseded' WHERE state = 'previewed'")
    )
    conn.execute(sa.text("UPDATE sheet_operations SET preview = '{}'::jsonb, export = NULL"))
    op.drop_constraint("sheet_base_pkey", "sheet_base", type_="primary")
    op.drop_constraint("sheet_base_mapping_id_fkey", "sheet_base", type_="foreignkey")
    op.drop_column("sheet_base", "mapping_id")
    op.drop_column("sheet_base", "sheet_id")
    op.alter_column("sheet_base", "link_id", nullable=False)
    op.create_primary_key("sheet_base_pkey", "sheet_base", ["link_id", "record_id"])
    op.create_foreign_key(
        "sheet_base_link_id_fkey",
        "sheet_base",
        "sheet_links",
        ["link_id"],
        ["id"],
        ondelete="CASCADE",
    )
    for name in ("collection", "sheet_title", "columns"):
        op.alter_column("sheet_links", name, nullable=False)
    op.drop_table("sheet_mappings")
