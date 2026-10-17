"""Shared JSON response class, outside `app.main` to avoid an import cycle."""

from __future__ import annotations

from typing import Any

import orjson
from fastapi.responses import JSONResponse


class ORJSONResponse(JSONResponse):
    """orjson drop-in for `JSONResponse`: faster, handles UUID and datetime natively;
    `OPT_NON_STR_KEYS` allows the UUID dict keys Pydantic sometimes produces."""

    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        return orjson.dumps(content, option=orjson.OPT_NON_STR_KEYS)
