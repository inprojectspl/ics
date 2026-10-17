"""`Accept-Language` route parameter. Routes default it to `None`, so they can
be called directly (tests, other routes) without a request."""

from __future__ import annotations

from typing import Annotated

from fastapi import Header

AcceptLanguage = Annotated[str | None, Header(include_in_schema=False)]
