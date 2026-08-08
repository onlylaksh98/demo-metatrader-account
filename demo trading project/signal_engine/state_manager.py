"""Stateful signal manager: creates, updates, versions, emits events."""
import asyncio
import json
from datetime import datetime
from typing import Optional, List
from loguru import logger

from database.models import (
    SessionLocal,
    Signal as SignalDB,
    SignalVersion,
    SignalTakeProfit,
    SignalEvent as SignalEventDB,
)
from signal_engine.models import MessageCategory, ParsedSignal, SignalStatus, TakeProfitLevel
from signal_engine.events import EventType, EventBus


class SignalStateManager:
    """Maintains active signals, edit history, and generates events."""

    def __init__(self, event_bus: Optional[EventBus] = None):
        self.session = SessionLocal()
        self.event_bus = event_bus
        logger.info("SignalStateManager initialized")

    def get_signal_by_telegram_id(self, telegram_message_id: int) -> Optional[SignalDB]:
        """Find an existing signal by its Telegram message ID."""
        if not telegram_message_id:
            return None
        return (
            self.session.query(SignalDB)
            .filter(SignalDB.telegram_message_id == telegram_message_id)
            .first()
        )

    def get_latest_active_signal(
        self, symbol: Optional[str] = None
    ) -> Optional[SignalDB]:
        """Get the most recent active signal, optionally filtered by symbol."""
        query = self.session.query(SignalDB).filter(
            SignalDB.status.notin_([SignalStatus.CLOSED.value, SignalStatus.CANCELLED.value])
        )
        if symbol:
            query = query.filter(SignalDB.symbol == symbol)
        return query.order_by(SignalDB.created_at.desc()).first()

    # ------------------------------------------------------------------
    # Public handlers
    # ------------------------------------------------------------------
    async def handle_new_message(self, parsed: ParsedSignal):
        """Dispatch a newly classified message to the correct handler."""
        if parsed.category == MessageCategory.NEW_SIGNAL:
            await self._create_signal(parsed)
        elif parsed.category in (
            MessageCategory.UPDATE_SL,
            MessageCategory.UPDATE_TP,
        ):
            await self._update_latest_signal(parsed)
        elif parsed.category == MessageCategory.MOVE_SL:
            await self._handle_move_sl(parsed)
        elif parsed.category == MessageCategory.BOOK_PROFIT:
            await self._handle_book_profit(parsed)
        elif parsed.category == MessageCategory.PARTIAL_CLOSE:
            await self._handle_partial_close(parsed)
        elif parsed.category == MessageCategory.EXIT:
            await self._handle_exit(parsed)
        elif parsed.category == MessageCategory.CANCEL_SIGNAL:
            await self._handle_cancel(parsed)
        elif parsed.category == MessageCategory.UNKNOWN:
            logger.warning(f"Unknown message type: {parsed.raw_text[:50]}...")

    async def handle_edit(self, parsed: ParsedSignal, existing_signal: SignalDB):
        """Handle an edited Telegram message. Preserves history, generates events."""
        logger.info(f"Handling edit for signal id={existing_signal.id}")

        # Snapshot current state before mutation
        self._save_version(existing_signal)

        old_sl = existing_signal.stop_loss
        old_tps = {tp.level: tp.price for tp in existing_signal.take_profits}
        old_status = existing_signal.status

        # Edit can also be a command (cancel / exit)
        if parsed.category == MessageCategory.CANCEL_SIGNAL:
            existing_signal.status = SignalStatus.CANCELLED.value
            existing_signal.updated_at = datetime.utcnow()
            self.session.commit()
            self._emit_event(EventType.SIGNAL_CANCELLED, existing_signal, {"reason": "edit"})
            return

        if parsed.category == MessageCategory.EXIT:
            existing_signal.status = SignalStatus.CLOSED.value
            existing_signal.updated_at = datetime.utcnow()
            self.session.commit()
            self._emit_event(EventType.CLOSE_TRADE, existing_signal, {"reason": "edit"})
            return

        # Update any fields present in the edited text
        if parsed.symbol:
            existing_signal.symbol = parsed.symbol
        if parsed.direction:
            existing_signal.direction = parsed.direction
            existing_signal.action = parsed.direction
        if parsed.entry_min is not None:
            existing_signal.entry_min = parsed.entry_min
            existing_signal.entry_price = parsed.entry_min
        if parsed.entry_max is not None:
            existing_signal.entry_max = parsed.entry_max
        if parsed.stop_loss is not None:
            existing_signal.stop_loss = parsed.stop_loss
        if parsed.take_profits:
            for tp in existing_signal.take_profits:
                self.session.delete(tp)
            for tp in parsed.take_profits:
                self.session.add(
                    SignalTakeProfit(
                        signal_id=existing_signal.id,
                        level=tp.level,
                        price=tp.price,
                    )
                )

        existing_signal.raw_text = parsed.raw_text
        existing_signal.version += 1
        existing_signal.updated_at = datetime.utcnow()

        self._update_status(existing_signal)
        self.session.commit()

        # Emit differential events
        if parsed.stop_loss is not None and old_sl != parsed.stop_loss:
            evt = (
                EventType.MOVE_STOP_LOSS
                if old_status == SignalStatus.OPEN.value
                else EventType.SIGNAL_UPDATED
            )
            self._emit_event(
                evt,
                existing_signal,
                {"old_sl": old_sl, "new_sl": parsed.stop_loss, "reason": "edit"},
            )

        if parsed.take_profits:
            new_tps = {tp.level: tp.price for tp in existing_signal.take_profits}
            if new_tps != old_tps:
                self._emit_event(
                    EventType.MOVE_TAKE_PROFIT,
                    existing_signal,
                    {"old_tps": old_tps, "new_tps": new_tps, "reason": "edit"},
                )

        self._emit_event(
            EventType.SIGNAL_UPDATED,
            existing_signal,
            {"version": existing_signal.version, "reason": "telegram_edit"},
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    async def _create_signal(self, parsed: ParsedSignal):
        signal = SignalDB(
            telegram_message_id=parsed.telegram_message_id,
            raw_text=parsed.raw_text,
            symbol=parsed.symbol,
            direction=parsed.direction,
            action=parsed.direction,
            entry_min=parsed.entry_min,
            entry_max=parsed.entry_max,
            entry_price=parsed.entry_min or parsed.entry_max,
            stop_loss=parsed.stop_loss,
            status=SignalStatus.PENDING.value,
            version=1,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self.session.add(signal)
        self.session.flush()  # obtain signal.id

        for tp in parsed.take_profits:
            self.session.add(
                SignalTakeProfit(
                    signal_id=signal.id, level=tp.level, price=tp.price
                )
            )

        self._update_status(signal)
        self.session.commit()
        self._emit_event(EventType.SIGNAL_CREATED, signal, {})
        logger.info(f"Created signal {signal.id} — {parsed.symbol} {parsed.direction}")

    async def _update_latest_signal(self, parsed: ParsedSignal):
        target = self.get_latest_active_signal(parsed.symbol)
        if not target:
            logger.warning("No active signal found to update with SL/TP")
            return

        old_sl = target.stop_loss
        old_tps = {tp.level: tp.price for tp in target.take_profits}

        if parsed.stop_loss is not None:
            target.stop_loss = parsed.stop_loss
            evt = (
                EventType.MOVE_STOP_LOSS
                if target.status == SignalStatus.OPEN.value
                else EventType.SIGNAL_UPDATED
            )
            self._emit_event(
                evt,
                target,
                {"old_sl": old_sl, "new_sl": parsed.stop_loss, "reason": "update"},
            )

        if parsed.take_profits:
            for tp in target.take_profits:
                self.session.delete(tp)
            for tp in parsed.take_profits:
                self.session.add(
                    SignalTakeProfit(
                        signal_id=target.id, level=tp.level, price=tp.price
                    )
                )
            self._emit_event(
                EventType.MOVE_TAKE_PROFIT,
                target,
                {
                    "old_tps": old_tps,
                    "new_tps": {tp.level: tp.price for tp in parsed.take_profits},
                    "reason": "update",
                },
            )

        target.updated_at = datetime.utcnow()
        self._update_status(target)
        self.session.commit()
        logger.info(f"Updated signal {target.id} with new SL/TP")

    async def _handle_move_sl(self, parsed: ParsedSignal):
        target = self.get_latest_active_signal()
        if not target:
            logger.warning("No active signal found for MOVE SL")
            return

        old_sl = target.stop_loss
        new_sl = None

        if parsed.move_sl_to in ("ENTRY", "BREAKEVEN", "BE"):
            new_sl = target.entry_min or target.entry_max or target.entry_price
        else:
            try:
                new_sl = float(parsed.move_sl_to)
            except ValueError:
                logger.error(f"Invalid MOVE SL target: {parsed.move_sl_to}")
                return

        if new_sl:
            target.stop_loss = new_sl
            target.updated_at = datetime.utcnow()
            self.session.commit()
            self._emit_event(
                EventType.MOVE_STOP_LOSS,
                target,
                {
                    "old_sl": old_sl,
                    "new_sl": new_sl,
                    "target": parsed.move_sl_to,
                    "reason": "command",
                },
            )
            logger.info(f"Moved SL for signal {target.id} to {new_sl}")

    async def _handle_book_profit(self, parsed: ParsedSignal):
        target = self.get_latest_active_signal()
        if not target:
            logger.warning("No active signal found for BOOK PROFIT")
            return

        percent = parsed.partial_percent or 100.0
        self._emit_event(
            EventType.PARTIAL_CLOSE,
            target,
            {"percent": percent, "reason": "book_profit"},
        )

        if percent >= 100:
            target.status = SignalStatus.CLOSED.value
            self._emit_event(
                EventType.CLOSE_TRADE, target, {"reason": "book_profit_full"}
            )
        else:
            target.status = SignalStatus.PARTIAL.value

        target.updated_at = datetime.utcnow()
        self.session.commit()
        logger.info(f"Booked {percent}% profit for signal {target.id}")

    async def _handle_partial_close(self, parsed: ParsedSignal):
        target = self.get_latest_active_signal()
        if not target:
            logger.warning("No active signal found for PARTIAL CLOSE")
            return

        percent = parsed.partial_percent or 50.0
        self._emit_event(
            EventType.PARTIAL_CLOSE,
            target,
            {"percent": percent, "reason": "partial_close"},
        )

        if percent >= 100:
            target.status = SignalStatus.CLOSED.value
            self._emit_event(
                EventType.CLOSE_TRADE, target, {"reason": "partial_close_full"}
            )
        else:
            target.status = SignalStatus.PARTIAL.value

        target.updated_at = datetime.utcnow()
        self.session.commit()
        logger.info(f"Partial close {percent}% for signal {target.id}")

    async def _handle_exit(self, parsed: ParsedSignal):
        target = self.get_latest_active_signal()
        if not target:
            logger.warning("No active signal found for EXIT")
            return

        target.status = SignalStatus.CLOSED.value
        target.updated_at = datetime.utcnow()
        self.session.commit()
        self._emit_event(EventType.CLOSE_TRADE, target, {"reason": "exit_now"})
        logger.info(f"Closed signal {target.id} via EXIT command")

    async def _handle_cancel(self, parsed: ParsedSignal):
        target = self.get_latest_active_signal()
        if not target:
            logger.warning("No active signal found for CANCEL")
            return

        target.status = SignalStatus.CANCELLED.value
        target.updated_at = datetime.utcnow()
        self.session.commit()
        self._emit_event(
            EventType.SIGNAL_CANCELLED, target, {"reason": "cancel_command"}
        )
        logger.info(f"Cancelled signal {target.id}")

    def _update_status(self, signal: SignalDB):
        """Auto-transition PENDING -> WAITING_ENTRY when enough fields are present."""
        if signal.status in (SignalStatus.CLOSED.value, SignalStatus.CANCELLED.value):
            return

        has_entry = (
            signal.entry_min is not None
            or signal.entry_max is not None
            or signal.entry_price is not None
        )
        has_direction = signal.direction is not None
        has_symbol = signal.symbol is not None

        if has_direction and has_symbol and has_entry:
            if signal.status == SignalStatus.PENDING.value:
                signal.status = SignalStatus.WAITING_ENTRY.value

    def _save_version(self, signal: SignalDB):
        """Snapshot the current signal state into the versions table."""
        version = SignalVersion(
            signal_id=signal.id,
            version=signal.version,
            symbol=signal.symbol,
            direction=signal.direction,
            entry_min=signal.entry_min,
            entry_max=signal.entry_max,
            stop_loss=signal.stop_loss,
            status=signal.status,
            raw_text=signal.raw_text or "",
        )
        self.session.add(version)
        self.session.commit()

    def _emit_event(self, event_type: EventType, signal: SignalDB, payload: dict):
        """Persist event to DB and publish to event bus."""
        event = SignalEventDB(
            signal_id=signal.id,
            event_type=event_type.value,
            payload=json.dumps(payload),
        )
        self.session.add(event)
        self.session.commit()

        if self.event_bus:
            bus_payload = {
                **payload,
                "signal_id": signal.id,
                "telegram_message_id": signal.telegram_message_id,
            }
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.event_bus.publish(event_type, bus_payload))
            except RuntimeError:
                pass  # No running event loop (sync context)

        logger.info(f"Event {event_type.value} for signal {signal.id}")

    def get_events(self, signal_id: int) -> List[SignalEventDB]:
        """Retrieve all events for a signal (useful for tests / debugging)."""
        return (
            self.session.query(SignalEventDB)
            .filter(SignalEventDB.signal_id == signal_id)
            .order_by(SignalEventDB.created_at)
            .all()
        )
