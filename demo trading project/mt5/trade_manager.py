"""High-level trade manager: subscribes to signal events and executes on MT5."""
import json
from datetime import datetime
from typing import Optional

from loguru import logger
import MetaTrader5 as mt5

from database.models import SessionLocal, Signal as SignalDB, SignalEvent, Trade
from signal_engine.events import EventType, EventBus
from mt5.connection import MT5Connection
from mt5.executor import MT5Executor
from mt5.symbol_resolver import SymbolResolver
from mt5.lot_calculator import LotCalculator


class TradeManager:
    """Wires signal events to MT5 execution via event-driven pub/sub."""

    def __init__(self):
        self.connection = MT5Connection()
        self.resolver = SymbolResolver()
        self.lot_calc = LotCalculator()
        self.executor = MT5Executor(self.resolver, self.lot_calc)
        self.session = SessionLocal()

    def subscribe(self, event_bus: EventBus):
        """Subscribe to all relevant signal events."""
        event_bus.subscribe(EventType.SIGNAL_CREATED, self._on_signal_created)
        event_bus.subscribe(EventType.SIGNAL_UPDATED, self._on_signal_updated)
        event_bus.subscribe(EventType.MOVE_STOP_LOSS, self._on_move_sl)
        event_bus.subscribe(EventType.MOVE_TAKE_PROFIT, self._on_move_tp)
        event_bus.subscribe(EventType.PARTIAL_CLOSE, self._on_partial_close)
        event_bus.subscribe(EventType.CLOSE_TRADE, self._on_close_trade)
        event_bus.subscribe(EventType.SIGNAL_CANCELLED, self._on_cancelled)
        logger.info("TradeManager subscribed to event bus")

    async def start(self):
        """Connect to MT5 and verify safety gates."""
        logger.info("TradeManager connecting to MT5...")
        if not self.connection.connect():
            raise RuntimeError("Failed to connect to MT5")
        if not self.connection.is_demo():
            self.connection.disconnect()
            raise RuntimeError("Account is not DEMO. Trading refused.")
        if not self.connection.is_trading_enabled():
            self.connection.disconnect()
            raise RuntimeError("Trading is not enabled")
        logger.info("TradeManager connected and ready")

    async def stop(self):
        """Disconnect from MT5."""
        self.connection.disconnect()
        logger.info("TradeManager stopped")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_signal(self, signal_id: int) -> Optional[SignalDB]:
        return self.session.query(SignalDB).filter(SignalDB.id == signal_id).first()

    def _get_trade_by_signal(self, signal_id: int) -> Optional[Trade]:
        return self.session.query(Trade).filter(Trade.signal_id == signal_id).first()

    def _is_complete(self, signal: SignalDB) -> bool:
        """A signal is trade-ready when it has symbol, direction, entry, and SL."""
        has_symbol = signal.symbol is not None
        has_direction = signal.direction is not None
        has_entry = (
            signal.entry_price is not None
            or signal.entry_min is not None
            or signal.entry_max is not None
        )
        has_sl = signal.stop_loss is not None
        return has_symbol and has_direction and has_entry and has_sl

    def _missing_fields(self, signal: SignalDB) -> list:
        missing = []
        if signal.symbol is None:
            missing.append("symbol")
        if signal.direction is None:
            missing.append("direction")
        if signal.entry_price is None and signal.entry_min is None and signal.entry_max is None:
            missing.append("entry")
        if signal.stop_loss is None:
            missing.append("SL")
        return missing

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------
    async def _on_signal_created(self, payload: dict):
        signal_id = payload.get("signal_id")
        logger.info(f"→ [SignalCreated] signal_id={signal_id}")
        signal = self._get_signal(signal_id)
        if not signal:
            logger.warning(f"  Signal {signal_id} not found in DB")
            return

        if self._get_trade_by_signal(signal_id):
            logger.info(f"  Trade already exists for signal {signal_id}. Skipping.")
            return

        if not self._is_complete(signal):
            missing = self._missing_fields(signal)
            logger.info(f"  Signal {signal_id} incomplete. Waiting for: {', '.join(missing)}")
            return

        logger.info(f"  Signal {signal_id} complete. Opening trade...")
        await self._open_trade(signal)

    async def _on_signal_updated(self, payload: dict):
        signal_id = payload.get("signal_id")
        logger.info(f"→ [SignalUpdated] signal_id={signal_id}")
        signal = self._get_signal(signal_id)
        if not signal:
            return

        if self._get_trade_by_signal(signal_id):
            logger.info(f"  Trade already exists for signal {signal_id}. No action needed.")
            return

        if not self._is_complete(signal):
            missing = self._missing_fields(signal)
            logger.info(f"  Signal {signal_id} still incomplete. Waiting for: {', '.join(missing)}")
            return

        logger.info(f"  Signal {signal_id} now complete. Opening trade...")
        await self._open_trade(signal)

    async def _on_move_sl(self, payload: dict):
        signal_id = payload.get("signal_id")
        logger.info(f"→ [MoveStopLoss] signal_id={signal_id}")
        trade = self._get_trade_by_signal(signal_id)
        if not trade or trade.status != "open" or not trade.mt5_ticket:
            logger.info(f"  No open trade to modify SL for signal {signal_id}")
            return
        new_sl = payload.get("new_sl")
        if new_sl is None:
            logger.warning(f"  MoveSL event missing new_sl payload")
            return
        try:
            self.executor.modify_sl(trade.mt5_ticket, float(new_sl))
            trade.stop_loss = float(new_sl)
            self.session.commit()
            logger.info(f"  Modified SL for trade {trade.id} to {new_sl}")
        except Exception as e:
            logger.error(f"  Failed to modify SL: {e}")

    async def _on_move_tp(self, payload: dict):
        signal_id = payload.get("signal_id")
        logger.info(f"→ [MoveTakeProfit] signal_id={signal_id}")
        trade = self._get_trade_by_signal(signal_id)
        if not trade or trade.status != "open" or not trade.mt5_ticket:
            logger.info(f"  No open trade to modify TP for signal {signal_id}")
            return
        signal = self._get_signal(signal_id)
        if not signal or not signal.take_profits:
            logger.warning(f"  MoveTP event but no TPs on signal {signal_id}")
            return
        new_tp = signal.take_profits[0].price
        try:
            self.executor.modify_tp(trade.mt5_ticket, new_tp)
            trade.take_profit = new_tp
            self.session.commit()
            logger.info(f"  Modified TP for trade {trade.id} to {new_tp}")
        except Exception as e:
            logger.error(f"  Failed to modify TP: {e}")

    async def _on_partial_close(self, payload: dict):
        signal_id = payload.get("signal_id")
        logger.info(f"→ [PartialClose] signal_id={signal_id}")
        trade = self._get_trade_by_signal(signal_id)
        if not trade or trade.status != "open" or not trade.mt5_ticket:
            logger.info(f"  No open trade to partially close for signal {signal_id}")
            return
        percent = payload.get("percent", 50.0)
        try:
            result = self.executor.partial_close(trade.mt5_ticket, float(percent))
            trade.status = "partial"
            self.session.commit()
            logger.info(f"  Partial close {percent}% for trade {trade.id}")
        except Exception as e:
            logger.error(f"  Failed partial close: {e}")

    async def _on_close_trade(self, payload: dict):
        signal_id = payload.get("signal_id")
        logger.info(f"→ [CloseTrade] signal_id={signal_id}")
        trade = self._get_trade_by_signal(signal_id)
        if not trade:
            logger.info(f"  No trade to close for signal {signal_id}")
            return
        try:
            if trade.status == "open" and trade.mt5_ticket:
                self.executor.close_position(trade.mt5_ticket)
            elif trade.status == "pending" and trade.mt5_order_ticket:
                self.executor.cancel_order(trade.mt5_order_ticket)
            trade.status = "closed"
            self.session.commit()
            logger.info(f"  Closed trade {trade.id}")
        except Exception as e:
            logger.error(f"  Failed to close trade: {e}")

    async def _on_cancelled(self, payload: dict):
        signal_id = payload.get("signal_id")
        logger.info(f"→ [SignalCancelled] signal_id={signal_id}")
        trade = self._get_trade_by_signal(signal_id)
        if not trade:
            logger.info(f"  No trade to cancel for signal {signal_id}")
            return
        try:
            if trade.status == "pending" and trade.mt5_order_ticket:
                self.executor.cancel_order(trade.mt5_order_ticket)
            elif trade.status == "open" and trade.mt5_ticket:
                self.executor.close_position(trade.mt5_ticket)
            trade.status = "cancelled"
            self.session.commit()
            logger.info(f"  Cancelled trade {trade.id}")
        except Exception as e:
            logger.error(f"  Failed to cancel trade: {e}")

    # ------------------------------------------------------------------
    # Trade execution
    # ------------------------------------------------------------------
    async def _open_trade(self, signal: SignalDB):
        entry = signal.entry_price
        entry_min = signal.entry_min
        entry_max = signal.entry_max

        if entry_min is not None and entry_max is not None:
            entry_for_calc = entry_min if signal.direction == "BUY" else entry_max
        else:
            entry_for_calc = entry or entry_min or entry_max

        try:
            result = self.executor.open_position(
                symbol=signal.symbol,
                direction=signal.direction,
                entry=entry,
                entry_min=entry_min,
                entry_max=entry_max,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profits[0].price if signal.take_profits else None,
            )
        except Exception as e:
            logger.error(f"  Failed to open position for signal {signal.id}: {e}")
            return

        mt5_result = result["result"]
        ticket = getattr(mt5_result, "order", None) or getattr(mt5_result, "deal", None)
        is_pending = result["order_type"] in (
            mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_SELL_LIMIT,
            mt5.ORDER_TYPE_BUY_STOP, mt5.ORDER_TYPE_SELL_STOP,
        )

        trade = Trade(
            signal_id=signal.id,
            symbol=result["symbol"],
            action=signal.direction,
            volume=result["volume"],
            entry_price=result["price"],
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profits[0].price if signal.take_profits else None,
            mt5_ticket=ticket if not is_pending else None,
            mt5_order_ticket=ticket if is_pending else None,
            order_type=result["order_type"],
            status="open" if not is_pending else "pending",
            created_at=datetime.utcnow(),
        )
        self.session.add(trade)
        self.session.commit()
        logger.info(
            f"  Trade opened: id={trade.id}, ticket={ticket}, "
            f"status={trade.status}, volume={trade.volume}, symbol={trade.symbol}"
        )

    # ------------------------------------------------------------------
    # Legacy dispatcher (for tests / direct DB event processing)
    # ------------------------------------------------------------------
    async def _process_event(self, event: SignalEvent):
        """Process a SignalEvent from DB (test entry point)."""
        logger.info(f"Processing event {event.id}: {event.event_type} for signal {event.signal_id}")
        payload = json.loads(event.payload or "{}")
        payload["signal_id"] = event.signal_id
        handler_map = {
            EventType.SIGNAL_CREATED.value: self._on_signal_created,
            EventType.SIGNAL_UPDATED.value: self._on_signal_updated,
            EventType.MOVE_STOP_LOSS.value: self._on_move_sl,
            EventType.MOVE_TAKE_PROFIT.value: self._on_move_tp,
            EventType.PARTIAL_CLOSE.value: self._on_partial_close,
            EventType.CLOSE_TRADE.value: self._on_close_trade,
            EventType.SIGNAL_CANCELLED.value: self._on_cancelled,
        }
        handler = handler_map.get(event.event_type)
        if handler:
            await handler(payload)
        else:
            logger.warning(f"No handler for event type: {event.event_type}")
