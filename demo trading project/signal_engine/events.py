"""Internal events emitted by the Signal Intelligence Engine."""
from dataclasses import dataclass, field
from typing import Dict, Any, Callable, List
from datetime import datetime
from enum import Enum

from loguru import logger


class EventType(Enum):
    SIGNAL_CREATED = "signal_created"
    SIGNAL_UPDATED = "signal_updated"
    SIGNAL_CANCELLED = "signal_cancelled"
    MOVE_STOP_LOSS = "move_stop_loss"
    MOVE_TAKE_PROFIT = "move_take_profit"
    PARTIAL_CLOSE = "partial_close"
    CLOSE_TRADE = "close_trade"


@dataclass
class SignalEvent:
    event_type: EventType
    signal_id: int
    telegram_message_id: int
    payload: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)


class EventBus:
    """Simple async pub/sub event bus."""

    def __init__(self):
        self._subscribers: Dict[EventType, List[Callable]] = {}

    def subscribe(self, event_type: EventType, callback: Callable):
        """Subscribe a callback to an event type."""
        self._subscribers.setdefault(event_type, []).append(callback)
        logger.info(f"EventBus: subscribed handler to {event_type.value}")

    async def publish(self, event_type: EventType, payload: Dict[str, Any]):
        """Publish an event to all subscribers."""
        handlers = self._subscribers.get(event_type, [])
        if not handlers:
            logger.debug(f"EventBus: no subscribers for {event_type.value}")
            return
        for handler in handlers:
            try:
                await handler(payload)
            except Exception as e:
                logger.error(f"EventBus: handler error for {event_type.value}: {e}")
