import asyncio
import os

from dotenv import load_dotenv
from loguru import logger

from database.models import init_db
from signal_engine.events import EventBus
from telegram.handlers import setup_engine
from telegram.listener import TelegramListener
from mt5.trade_manager import TradeManager

load_dotenv()

logger.add("logs/telegram2mt5.log", rotation="1 MB", retention="10 days")


async def main():
    logger.info("=" * 50)
    logger.info("Telegram2MT5 MVP starting (event-driven)...")
    logger.info("=" * 50)

    # Initialize database
    init_db()
    logger.info("Database initialized")

    # Create event bus
    event_bus = EventBus()
    logger.info("Event bus created")

    # Wire signal engine to event bus
    setup_engine(event_bus=event_bus)
    logger.info("Signal engine wired to event bus")

    # MT5 trade manager subscribes to events
    trade_manager = TradeManager()
    trade_manager.subscribe(event_bus)
    try:
        await trade_manager.start()
    except Exception as e:
        logger.error(f"TradeManager failed to start: {e}")
        return

    # Start Telegram listener
    listener = TelegramListener()
    try:
        await listener.start()
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user")
    finally:
        await listener.stop()
        await trade_manager.stop()


if __name__ == "__main__":
    os.makedirs("logs", exist_ok=True)
    asyncio.run(main())
