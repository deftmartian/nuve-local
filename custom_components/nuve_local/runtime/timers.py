"""Single-shot event-loop timer used for liveness and bootstrap expiry."""

from __future__ import annotations

import asyncio
from collections.abc import Callable


class OneShotTimer:
    """Own at most one scheduled callback and its cancellation."""

    __slots__ = ("_handle",)

    def __init__(self) -> None:
        self._handle: asyncio.TimerHandle | None = None

    @property
    def scheduled(self) -> bool:
        """Return whether a callback is still scheduled."""

        return self._handle is not None

    def start(self, delay: float, callback: Callable[[], object]) -> None:
        """Replace any scheduled callback with ``callback`` after ``delay`` seconds."""

        self.cancel()
        self._handle = asyncio.get_running_loop().call_later(delay, callback)

    def cancel(self) -> None:
        """Cancel and forget the scheduled callback, if any."""

        if self._handle is not None:
            self._handle.cancel()
            self._handle = None

    def forget(self) -> None:
        """Forget a callback that has already fired, without cancelling it."""

        self._handle = None
