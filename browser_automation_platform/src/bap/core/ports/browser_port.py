from __future__ import annotations

from abc import ABC, abstractmethod

from bap.core.domain.models import TabHandle, TabId, TabProfile, ViewportSize

__all__ = [
    "TabHandle",
    "TabId",
    "TabProfile",
    "ViewportSize",
    "BrowserManagerError",
    "BrowserNotStartedError",
    "DuplicateTabError",
    "TabLimitExceededError",
    "TabNotFoundError",
    "BrowserPort",
]


class BrowserManagerError(Exception):
    """Base class for all BrowserPort errors."""


class BrowserNotStartedError(BrowserManagerError):
    pass


class DuplicateTabError(BrowserManagerError):
    pass


class TabLimitExceededError(BrowserManagerError):
    pass


class TabNotFoundError(BrowserManagerError):
    pass


class BrowserPort(ABC):
    """Lifecycle and tab management contract for a browser engine adapter.

    Implementations own exactly one underlying browser process and any number
    of tabs (up to their configured limit). Capture and input actions are
    deliberately out of scope here — they live behind CapturePort and
    ActionHandlerPort, which operate on the TabHandle this port returns.
    """

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def open_tab(self, profile: TabProfile) -> TabHandle: ...

    @abstractmethod
    async def navigate(self, tab: TabHandle, url: str) -> None: ...

    @abstractmethod
    async def close_tab(self, tab: TabHandle) -> None: ...

    @abstractmethod
    def list_tabs(self) -> list[TabId]: ...
