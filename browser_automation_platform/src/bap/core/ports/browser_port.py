from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

TabId = str


@dataclass(frozen=True)
class ViewportSize:
    width: int = 1920
    height: int = 1080


@dataclass(frozen=True)
class TabProfile:
    id: TabId
    start_url: str | None = None
    viewport: ViewportSize = field(default_factory=ViewportSize)


@dataclass(frozen=True)
class TabHandle:
    tab_id: TabId
    native: Any


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
