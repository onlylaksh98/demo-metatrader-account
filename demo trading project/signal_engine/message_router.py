"""Routes classified messages to the signal state manager."""
from datetime import datetime
from typing import Optional
from loguru import logger

from signal_engine.classifier import SignalClassifier
from signal_engine.state_manager import SignalStateManager


class MessageRouter:
    """Receives raw Telegram messages, classifies them, and dispatches to state manager."""

    def __init__(self, state_manager: SignalStateManager):
        self.classifier = SignalClassifier()
        self.state_manager = state_manager

    async def route(
        self,
        text: str,
        telegram_message_id: int,
        edited: bool = False,
        date: Optional[datetime] = None,
    ):
        """Route a raw message to the appropriate handler."""
        logger.info(f"Routing msg_id={telegram_message_id} edited={edited}")

        existing_signal = self.state_manager.get_signal_by_telegram_id(telegram_message_id)

        # Duplicate (same ID, not edited) -> ignore
        if existing_signal and not edited:
            logger.warning(f"Duplicate message {telegram_message_id} ignored")
            return

        parsed = self.classifier.classify(text, telegram_message_id)

        if edited and existing_signal:
            await self.state_manager.handle_edit(parsed, existing_signal)
        else:
            await self.state_manager.handle_new_message(parsed)
