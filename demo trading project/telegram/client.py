"""Telegram client wrapper using Telethon."""
import os

from dotenv import load_dotenv
from loguru import logger
from telethon import TelegramClient

load_dotenv()

API_ID = int(os.getenv("API_ID", 0))
API_HASH = os.getenv("API_HASH", "")
PHONE = os.getenv("PHONE", "")
SESSION_NAME = os.getenv("TELEGRAM_SESSION_NAME", "telegram2mt5_session")


class TelegramClientWrapper:
    """Wraps Telethon client with auto-login using .env credentials."""

    def __init__(self):
        self.client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
        logger.info("Telegram client initialized")

    async def start(self):
        """Start the client. Prompts for login code if session is missing."""
        await self.client.start(phone=lambda: PHONE)
        me = await self.client.get_me()
        logger.info(f"Logged in as {me.first_name} (@{me.username})")

    async def stop(self):
        await self.client.disconnect()
        logger.info("Telegram client stopped")
