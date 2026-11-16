"""All existing HTTP version writers share the optional compare-and-set contract."""

import pytest
from sqlalchemy import select

from app.collections_io import list_version_files, read_bytes_at_version
from app.config import get_settings
from app.models import AssetVersion
from tests.conftest import mk_md_collection

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("fs_storage")]
OPERATIONS = ["edit", "add", "empty", "delete", "move", "replace", "restore"]


async def write(client, asset_id, operation, expected_version):
    base = f"/api/assets/{asset_id}"
    expected = {} if expected_version is None else {"expected_version": expected_version}
    if operation == "edit":
        return await client.put(
            f"{base}/content", json={"path": "index.md", "content": "third", **expected}
        )
    if operation == "empty":
        return await client.post(f"{base}/files/empty", json={"path": "new.md", **expected})
    if operation == "move":
        return await client.patch(
            f"{base}/files/move",
            json={"from_path": "other.md", "to_path": "moved.md", **expected},
        )
    if operation == "delete":
        return await client.delete(f"{base}/files", params={"path": "other.md", **expected})
    if operation == "restore":
        return await client.post(f"{base}/versions/1/restore", params=expected)
    if operation == "add":
        return await client.post(
            f"{base}/files",
            data={"path": "new.md", **expected},
            files={"file": ("new.md", b"new", "text/markdown")},
        )
    assert operation == "replace"
    return await client.post(
        f"{base}/versions",
        data={"paths": ["index.md"], **expected},
        files=[("files", ("index.md", b"replacement", "text/markdown"))],
    )


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("expected_version", [2, None, 1, 3, 0])
async def test_version_writers_honor_expected_version(client, session, operation, expected_version):
    owner, asset = await mk_md_collection(
        client, session, {"index.md": "first", "other.md": "keep"}
    )
    session.add(
        AssetVersion(
            asset_id=asset.id,
            version=1,
            storage_prefix=f"{asset.storage_prefix}/v1",
            size_bytes=9,
            created_by=owner.id,
        )
    )
    await session.commit()
    second = await client.put(
        f"/api/assets/{asset.id}/content", json={"path": "index.md", "content": "second"}
    )
    assert second.status_code == 201, second.text
    assert second.json()["version"] == 2

    response = await write(client, asset.id, operation, expected_version)
    if expected_version in (1, 3):
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "version_conflict"
    elif expected_version == 0:
        assert response.status_code == 422, response.text
    else:
        assert response.status_code in (200, 201), response.text
        assert response.json()["version"] == 3

    await session.refresh(asset)
    rejected = expected_version in (0, 1, 3)
    assert asset.version == (2 if rejected else 3)
    versions = (
        await session.scalars(
            select(AssetVersion.version)
            .where(AssetVersion.asset_id == asset.id)
            .order_by(AssetVersion.version)
        )
    ).all()
    assert versions == ([1, 2] if rejected else [1, 2, 3])
    settings = get_settings()
    assert await read_bytes_at_version(asset, 1, "index.md", settings) == b"first"
    assert await read_bytes_at_version(asset, 2, "index.md", settings) == b"second"
    if rejected:
        assert await list_version_files(asset, 3, settings) == []
