"""Telegram channel listener. Wires client + handlers."""
import os

from dotenv import load_dotenv
from loguru import logger
from telethon import events

from telegram.client import TelegramClientWrapper
from telegram.handlers import handle_new_message, handle_edit_message

load_dotenv()

CHANNEL_ID = os.getenv("CHANNEL_ID", "")


class TelegramListener:
    """Listens to a single Telegram channel for new and edited messages."""

    def __init__(self):
        self.wrapper = TelegramClientWrapper()
        self.channel_id = CHANNEL_ID
        logger.info(f"TelegramListener initialized for channel: {self.channel_id}")

    async def start(self):
        await self.wrapper.start()

        # Resolve channel entity if CHANNEL_ID is a username
        try:
            entity = await self.wrapper.client.get_entity(self.channel_id)
            logger.info(f"Resolved channel: {getattr(entity, 'title', self.channel_id)}")
        except Exception as e:
            logger.error(f"Failed to resolve channel {self.channel_id}: {e}")
            raise

        # Register handlers for this specific channel
        self.wrapper.client.add_event_handler(
            handle_new_message,
            events.NewMessage(chats=entity),
        )
        self.wrapper.client.add_event_handler(
            handle_edit_message,
            events.MessageEdited(chats=entity),
        )

        logger.info("Listening for new and edited messages...")
        await self.wrapper.client.run_until_disconnected()

    async def stop(self):
        await self.wrapper.stop()
