"""Telegram event handlers for new and edited messages."""
from datetime import datetime

from loguru import logger
from telethon import events

from database.models import SessionLocal, Message
from signal_engine.message_router import MessageRouter
from signal_engine.state_manager import SignalStateManager

_state_manager: SignalStateManager | None = None
_router: MessageRouter | None = None


def setup_engine(event_bus=None):
    """Initialize signal engine with optional event bus. Call once before starting listener."""
    global _state_manager, _router
    _state_manager = SignalStateManager(event_bus=event_bus)
    _router = MessageRouter(_state_manager)
    logger.info("Signal engine initialized via setup_engine")
    return _state_manager


# Default instances for backward compatibility (will be replaced by setup_engine)
if _state_manager is None:
    _state_manager = SignalStateManager()
    _router = MessageRouter(_state_manager)


def _print_message(telegram_message_id, date, channel_title, edited, text):
    """Print message details to console."""
    print("-" * 34)
    print(f"Message ID: {telegram_message_id}")
    print(f"Date:       {date}")
    print(f"Channel:    {channel_title}")
    print(f"Edited:     {edited}")
    print(f"Raw Text:   {text}")
    print("-" * 34)


async def handle_new_message(event):
    """Handler for new messages."""
    msg = event.message
    channel = await event.get_chat()
    channel_title = getattr(channel, "title", "Unknown")

    logger.info(f"Telegram received: msg_id={msg.id} from {channel_title}")

    _print_message(
        telegram_message_id=msg.id,
        date=msg.date,
        channel_title=channel_title,
        edited=False,
        text=msg.text or "",
    )

    # Save raw message to DB
    session = SessionLocal()
    try:
        existing = (
            session.query(Message)
            .filter(Message.telegram_message_id == msg.id)
            .first()
        )
        if existing:
            logger.debug(f"Message {msg.id} already in DB, skipping raw save")
        else:
            db_msg = Message(
                telegram_message_id=msg.id,
                channel_id=channel.id,
                date=msg.date,
                edited=False,
                text=msg.text or "",
            )
            session.add(db_msg)
            session.commit()
            logger.info(f"Raw message {msg.id} saved to DB")
    except Exception as e:
        logger.error(f"Failed to save message {msg.id}: {e}")
    finally:
        session.close()

    # Route to signal engine
    try:
        await _router.route(
            text=msg.text or "",
            telegram_message_id=msg.id,
            edited=False,
            date=msg.date,
        )
    except Exception as e:
        logger.error(f"Signal engine error for message {msg.id}: {e}")


async def handle_edit_message(event):
    """Handler for edited messages."""
    msg = event.message
    channel = await event.get_chat()
    channel_title = getattr(channel, "title", "Unknown")

    logger.info(f"Telegram edited: msg_id={msg.id} from {channel_title}")

    _print_message(
        telegram_message_id=msg.id,
        date=msg.date,
        channel_title=channel_title,
        edited=True,
        text=msg.text or "",
    )

    # Update raw message in DB
    session = SessionLocal()
    try:
        existing = (
            session.query(Message)
            .filter(Message.telegram_message_id == msg.id)
            .first()
        )
        if existing:
            existing.text = msg.text or ""
            existing.edited = True
            session.commit()
            logger.info(f"Raw message {msg.id} updated in DB (edited)")
        else:
            db_msg = Message(
                telegram_message_id=msg.id,
                channel_id=channel.id,
                date=msg.date,
                edited=True,
                text=msg.text or "",
            )
            session.add(db_msg)
            session.commit()
    except Exception as e:
        logger.error(f"Failed to update edited message {msg.id}: {e}")
    finally:
        session.close()

    # Route to signal engine
    try:
        await _router.route(
            text=msg.text or "",
            telegram_message_id=msg.id,
            edited=True,
            date=msg.date,
        )
    except Exception as e:
        logger.error(f"Signal engine error for edited message {msg.id}: {e}")
