"""Google Sheets links of micro-applications (ADR-0031, ADR-0033).

A person's Google grant, the link of an app to one spreadsheet file, the
mappings of its collections to the file's tabs, the agreed value of every
linked cell at the last sync (the base of the three-way comparison) and the
sync operations. All of it is platform data: the app's own database holds
only its records, changed through the broker.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

TS = TIMESTAMP(timezone=True)


class GoogleGrant(Base):
    """One Google account per ICS user, bound by the verified `sub`; the
    refresh token is encrypted with `secret_box` (purpose `google-grant`)."""

    __tablename__ = "google_grants"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    subject: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(320))
    scopes: Mapped[str] = mapped_column(Text)
    refresh_token_enc: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now())


class SheetLink(Base):
    """One app <-> one spreadsheet file. An app has at most one link and a
    spreadsheet at most one, so ICS is never one of several writers of the
    same file. What is linked is in `SheetMapping`s; one sync reads and
    writes the whole file."""

    __tablename__ = "sheet_links"
    __table_args__ = (
        CheckConstraint(
            "account_mode IN ('owner_account', 'per_user')", name="ck_sheet_links_account_mode"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), unique=True)
    spreadsheet_id: Mapped[str] = mapped_column(String(128), unique=True)
    account_mode: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Automatic sync: ICS runs it as the owner when the broker reports the
    # collection changed and, while the app is awake, on an interval for
    # edits typed into the sheet (ADR-0032). `app_changed_at`: the last
    # report of a write to a linked collection; `auto_checked_at`: the last run;
    # `auto_next_at`: no run before it (a retry's backoff, a waiting preview);
    # `auto_sheet_hash`: the linked columns as a run last found them with
    # nothing to do, so an idle run reads only Google.
    auto_sync: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    app_changed_at: Mapped[datetime | None] = mapped_column(TS)
    auto_checked_at: Mapped[datetime | None] = mapped_column(TS)
    auto_next_at: Mapped[datetime | None] = mapped_column(TS)
    auto_sheet_hash: Mapped[str | None] = mapped_column(String(64))
    # Why the last automatic run stopped short (a code); None when it went through.
    auto_error: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now())


class SheetMapping(Base):
    """One app collection <-> one tab, or several tabs with the same linked
    headers (records split by month, state, team...), of the link's file.
    `tabs`: [{sheet_id, title, append?}]; `sheet_id` is Google's tab id, so a
    renamed tab stays linked (None until the first read pins it by `title`);
    `append` marks the tab new records go to. `columns`: [{field, header,
    owner}] with owner `sheet`, `app` or `both`. The sheet carries no ids:
    rows are matched to records by `key_field` (a linked field unique across
    the tabs; required with more than one tab), by content and position
    otherwise. `tab_field`: a string field that takes the name of the tab a
    record's row is in."""

    __tablename__ = "sheet_mappings"
    __table_args__ = (UniqueConstraint("link_id", "collection"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    link_id: Mapped[UUID] = mapped_column(
        ForeignKey("sheet_links.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    collection: Mapped[str] = mapped_column(String(64))
    tabs: Mapped[list] = mapped_column(JSONB)
    key_field: Mapped[str | None] = mapped_column(String(64))
    tab_field: Mapped[str | None] = mapped_column(String(64))
    columns: Mapped[list] = mapped_column(JSONB)


class SheetBase(Base):
    """The agreed value of each linked field of a record at the last sync and
    the tab and row it was last seen in (a hint when its content changed)."""

    __tablename__ = "sheet_base"

    mapping_id: Mapped[UUID] = mapped_column(
        ForeignKey("sheet_mappings.id", ondelete="CASCADE"), primary_key=True
    )
    record_id: Mapped[UUID] = mapped_column(primary_key=True)
    values: Mapped[dict] = mapped_column(JSONB)
    sheet_id: Mapped[int | None] = mapped_column(Integer)
    row: Mapped[int | None] = mapped_column(Integer)


class SheetOperation(Base):
    """A preview of the whole file and, once applied, its outcome: `state` for
    the app's data, `google_status` for the write to the sheet, which may stay
    `uncertain` when Google's answer is lost. `preview` and `export` hold one
    part per mapping under `mappings`, keyed by the mapping's id."""

    __tablename__ = "sheet_operations"
    __table_args__ = (
        CheckConstraint(
            "state IN ('previewed', 'applying', 'applied', 'stale', 'superseded', 'failed')",
            name="ck_sheet_operations_state",
        ),
        CheckConstraint(
            "google_status IN ('none', 'pending', 'confirmed', 'uncertain', 'failed')",
            name="ck_sheet_operations_google_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    link_id: Mapped[UUID] = mapped_column(
        ForeignKey("sheet_links.id", ondelete="CASCADE"), index=True
    )
    link_revision: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # Whose Google grant reads and writes: the owner's or the actor's.
    google_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    state: Mapped[str] = mapped_column(String(16), default="previewed")
    google_status: Mapped[str] = mapped_column(String(16), default="none")
    # Counts of the preview, kept when its details are dropped.
    summary: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    preview: Mapped[dict] = mapped_column(JSONB)
    decisions: Mapped[dict | None] = mapped_column(JSONB)
    export: Mapped[dict | None] = mapped_column(JSONB)
    result: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(String(64))
    auto: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now())
