"""routes/relations package (ADR-0016): every module registers its endpoints
on the shared `router` from `_router.py`."""

from app.routes.relations import (  # noqa: F401  (register endpoints)
    asset_relations,
    context,
    external,
    graph,
    projects,
)
from app.routes.relations._router import router

__all__ = ["router"]
