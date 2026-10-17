"""routes/assets package: one module per concern plus shared `_helpers`.

Re-exports below serve `main.py`, tests and the lazy imports in
`routes.shares` and `routes.html_viewer`.
"""

# Side-effect imports: these modules register endpoints on the routers below.
# `entry` is the one asset endpoint that serves anonymous callers, hence its
# own file; the rest are split out for the file size budget.
from app.routes.assets import (  # noqa: F401
    doc_view,
    documents,
    entry,
    link_titles,
    metadata,
    project_shares,
    summary,
    watch,
)
from app.routes.assets._helpers import (
    _doc_payload_for,
    _stream_source,
    assert_bundle_renderable_for_visitors,
    is_html_doc,
    serve_bundle_file,
)
from app.routes.assets.content import (
    EditContentIn,
    add_file_to_collection,
    edit_content,
)
from app.routes.assets.content import router as content_router
from app.routes.assets.crud import router as crud_router
from app.routes.assets.crud import (
    upload_collection,
    upload_html_bundle,
    upload_markdown,
)
from app.routes.assets.file_move import move_file_in_collection
from app.routes.assets.ocr import request_ocr
from app.routes.assets.pins import pin_asset, unpin_asset
from app.routes.assets.shares import (
    CreateAssetShareIn,
    PatchAssetProjectIn,
    create_asset_share,
    delete_asset_share,
    list_asset_shares,
    patch_asset_project,
)
from app.routes.assets.shares import router as shares_router
from app.routes.assets.versions import (
    create_version,
    diff_versions,
    restore_version,
)
from app.routes.assets.versions import router as versions_router
from app.routes.assets.view import list_my_assets, search_my_assets
from app.routes.assets.view import router as view_router

__all__ = [  # noqa: RUF022 - grouped by consumer
    # Routers (registered in main.py; order matters: view before crud, so the
    # static paths /search and "" win over the dynamic /{asset_id}).
    "view_router",
    "crud_router",
    "versions_router",
    "content_router",
    "shares_router",
    # Pydantic models, exported for tests
    "CreateAssetShareIn",
    "EditContentIn",
    "PatchAssetProjectIn",
    # Helpers, used by routes.shares, routes.html_viewer and tests
    "assert_bundle_renderable_for_visitors",
    "is_html_doc",
    "serve_bundle_file",
    "_doc_payload_for",
    "_stream_source",
    # Route functions, used by tests
    "add_file_to_collection",
    "create_asset_share",
    "create_version",
    "delete_asset_share",
    "diff_versions",
    "edit_content",
    "list_asset_shares",
    "list_my_assets",
    "move_file_in_collection",
    "patch_asset_project",
    "pin_asset",
    "request_ocr",
    "restore_version",
    "search_my_assets",
    "unpin_asset",
    "upload_collection",
    "upload_html_bundle",
    "upload_markdown",
]
