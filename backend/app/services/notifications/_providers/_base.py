"""Abstract interface of a binding sync notification provider. A new provider is
a `NotificationProvider` subclass in `_providers/{name}.py`, an instance in
`_providers/__init__.py::_INSTANCES` and a `NotificationProviderId` value.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from .._types import NotificationContext, NotificationProviderId


class NotificationProvider(ABC):
    """`send()` never raises: it runs after the sync commit, so failures are
    caught and logged. `accepts_url()` does no I/O: it runs in DTO validation.
    """

    id: ClassVar[NotificationProviderId]
    display_name: ClassVar[str]
    url_hint: ClassVar[str]

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # Checks __dict__, not annotations: the value must actually be assigned.
        missing = [attr for attr in ("id", "display_name", "url_hint") if attr not in cls.__dict__]
        if missing:
            raise TypeError(f"{cls.__name__} must define ClassVar: {', '.join(missing)}")

    @abstractmethod
    def accepts_url(self, url: str) -> bool:
        """True iff the URL is formally valid for this provider. Sync."""

    @abstractmethod
    async def send(self, url: str, ctx: NotificationContext) -> None:
        """Send the payload. Silently swallow any failure (network, 5xx, parse)."""
