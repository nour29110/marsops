"""In-memory telemetry pub/sub broadcaster for the MarsOps Web API.

Provides :class:`TelemetryBroadcaster`, a lightweight asyncio-based
publish/subscribe hub that allows multiple WebSocket clients to receive
telemetry events from a single mission run.  A module-level singleton
:data:`broadcaster` is exported for use by the FastAPI application.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

_MAX_QUEUE_SIZE: int = 256


class TelemetryBroadcaster:
    """In-memory pub/sub broadcaster for telemetry events.

    Maintains a list of :class:`asyncio.Queue` subscribers.  Events pushed
    via :meth:`broadcast` are forwarded to every subscriber non-blocking.
    If a subscriber's queue is full the event is silently dropped for that
    subscriber rather than blocking the caller.

    Attributes:
        _subscribers: Active subscriber queues.
    """

    def __init__(self) -> None:
        """Initialise with an empty subscriber list."""
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Create and register a new subscriber queue.

        Returns:
            A new :class:`asyncio.Queue` that will receive every subsequent
            :meth:`broadcast` event.
        """
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_MAX_QUEUE_SIZE)
        self._subscribers.append(queue)
        logger.debug("TelemetryBroadcaster: new subscriber (%d total)", len(self._subscribers))
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Remove a subscriber queue.

        Args:
            queue: The queue previously returned by :meth:`subscribe`.
        """
        try:
            self._subscribers.remove(queue)
            logger.debug(
                "TelemetryBroadcaster: subscriber removed (%d remain)",
                len(self._subscribers),
            )
        except ValueError:
            logger.warning("TelemetryBroadcaster: unsubscribe called for unknown queue")

    async def broadcast(self, event: dict[str, Any]) -> None:
        """Push an event onto every registered subscriber queue.

        Uses ``await queue.put`` to enqueue events.  If the subscriber's
        bounded queue raises :exc:`asyncio.QueueFull` the event is dropped for
        that subscriber and a warning is logged.

        Args:
            event: A JSON-serialisable dict representing the telemetry event.
        """
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("TelemetryBroadcaster: subscriber queue full, event dropped")


broadcaster: TelemetryBroadcaster = TelemetryBroadcaster()
