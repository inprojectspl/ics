"""A project has at most one owner, enforced by the database."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Project, ProjectMember
from app.slug import generate_slug
from tests.conftest import mk_user


async def test_second_project_owner_rejected(session):
    first = await mk_user(session)
    second = await mk_user(session)
    project = Project(slug=generate_slug(), name="p")
    session.add(project)
    await session.flush()
    session.add(ProjectMember(project_id=project.id, user_id=first.id, role="owner"))
    await session.flush()

    session.add(ProjectMember(project_id=project.id, user_id=second.id, role="owner"))
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()


async def test_owner_and_editor_coexist(session):
    owner = await mk_user(session)
    editor = await mk_user(session)
    project = Project(slug=generate_slug(), name="p")
    session.add(project)
    await session.flush()
    session.add_all(
        [
            ProjectMember(project_id=project.id, user_id=owner.id, role="owner"),
            ProjectMember(project_id=project.id, user_id=editor.id, role="editor"),
        ]
    )
    await session.flush()
