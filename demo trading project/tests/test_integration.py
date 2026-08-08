"""Integration tests for the full Telegram → Signal → MT5 event-driven flow."""
import os
import sys
import asyncio
from unittest.mock import MagicMock

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from tests.conftest import mt5_mock

# ------------------------------------------------------------------
# Configure shared mock for integration tests
# ------------------------------------------------------------------
acc_mock = MagicMock()
acc_mock.login = 12345
acc_mock.trade_mode = 0  # DEMO
acc_mock.trade_allowed = 1
mt5_mock.account_info.return_value = acc_mock

term_mock = MagicMock()
term_mock.connected = True
term_mock.trade_allowed = True
term_mock.tradeapi_disabled = False
# Mock _asdict() method to return actual attributes
term_mock._asdict.return_value = {
    'connected': True,
    'trade_allowed': True,
    'tradeapi_disabled': False,
    'dlls_allowed': True,
    'community_account': False,
}
mt5_mock.terminal_info.return_value = term_mock

sym_mock = MagicMock()
sym_mock.trade_tick_size = 0.01
sym_mock.trade_tick_value = 1.0
sym_mock.volume_min = 0.01
sym_mock.volume_max = 100.0
sym_mock.volume_step = 0.01
sym_mock.visible = True
mt5_mock.symbol_info.return_value = sym_mock
mt5_mock.symbol_select.return_value = True

tick_mock = MagicMock()
tick_mock.ask = 3341.0
tick_mock.bid = 3340.5
mt5_mock.symbol_info_tick.return_value = tick_mock

order_result = MagicMock()
order_result.retcode = 10009
order_result.order = 111111
order_result.deal = 222222
order_result.comment = "Done"
mt5_mock.order_send.return_value = order_result

pos_mock = MagicMock()
pos_mock.ticket = 222222
pos_mock.symbol = "XAUUSD"
pos_mock.type = 0
pos_mock.volume = 0.06
pos_mock.volume_step = 0.01
pos_mock.price_current = 3341.0
pos_mock.sl = 3334.0
pos_mock.tp = 3350.0
mt5_mock.positions_get.return_value = (pos_mock,)

# Now import project modules
from database.models import init_db, SessionLocal, Signal, Trade
from signal_engine.events import EventBus
from signal_engine.classifier import SignalClassifier
from signal_engine.state_manager import SignalStateManager
from mt5.trade_manager import TradeManager


@pytest.fixture(autouse=True)
def reset_mock():
    """Reset mock return values before each integration test."""
    mt5_mock.account_info.return_value = acc_mock
    mt5_mock.symbol_info.return_value = sym_mock
    mt5_mock.symbol_info_tick.return_value = tick_mock
    mt5_mock.positions_get.return_value = (pos_mock,)
    mt5_mock.order_send.return_value = order_result
    yield


@pytest.fixture(scope="function")
def db():
    init_db()
    yield SessionLocal()


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def state_manager(event_bus):
    return SignalStateManager(event_bus=event_bus)


@pytest.fixture
def trade_manager(event_bus):
    tm = TradeManager()
    tm.subscribe(event_bus)
    return tm


@pytest.fixture
def classifier():
    return SignalClassifier()


class TestIntegration:
    def test_incomplete_signal_waits_then_opens(self, db, event_bus, state_manager, trade_manager, classifier):
        async def _test():
            await trade_manager.start()

            # Step 1: Incomplete signal (no SL)
            parsed = classifier.classify("BUY GOLD\n3340", telegram_message_id=1)
            await state_manager.handle_new_message(parsed)
            await asyncio.sleep(0.05)

            signal = db.query(Signal).filter(Signal.telegram_message_id == 1).first()
            assert signal.status == "WAITING_ENTRY"
            assert signal.stop_loss is None
            assert db.query(Trade).filter(Trade.signal_id == signal.id).first() is None

            # Step 2: SL arrives — signal completes, trade opens
            parsed_sl = classifier.classify("SL 3334", telegram_message_id=2)
            await state_manager.handle_new_message(parsed_sl)
            await asyncio.sleep(0.05)

            db.refresh(signal)
            assert signal.stop_loss == 3334.0

            trade = db.query(Trade).filter(Trade.signal_id == signal.id).first()
            assert trade is not None
            assert trade.symbol == "XAUUSD"
            assert trade.action == "BUY"
            assert trade.status in ("open", "pending")

            await trade_manager.stop()
        asyncio.run(_test())

    def test_complete_signal_opens_immediately(self, db, event_bus, state_manager, trade_manager, classifier):
        async def _test():
            await trade_manager.start()

            parsed = classifier.classify(
                "BUY GOLD\n3340\nSL 3334\nTP1 3350", telegram_message_id=3
            )
            await state_manager.handle_new_message(parsed)
            await asyncio.sleep(0.05)

            signal = db.query(Signal).filter(Signal.telegram_message_id == 3).first()
            assert signal is not None

            trade = db.query(Trade).filter(Trade.signal_id == signal.id).first()
            assert trade is not None
            assert trade.action == "BUY"
            assert trade.stop_loss == 3334.0

            await trade_manager.stop()
        asyncio.run(_test())

    def test_move_sl_modifies_trade(self, db, event_bus, state_manager, trade_manager, classifier):
        async def _test():
            await trade_manager.start()

            parsed = classifier.classify("BUY GOLD\n3340\nSL 3334", telegram_message_id=4)
            await state_manager.handle_new_message(parsed)
            await asyncio.sleep(0.05)

            signal = db.query(Signal).filter(Signal.telegram_message_id == 4).first()
            trade = db.query(Trade).filter(Trade.signal_id == signal.id).first()
            trade.status = "open"
            trade.mt5_ticket = 222222
            db.commit()

            parsed_move = classifier.classify("MOVE SL TO ENTRY", telegram_message_id=5)
            await state_manager.handle_new_message(parsed_move)
            await asyncio.sleep(0.05)

            db.refresh(trade)
            assert trade.stop_loss == 3340.0

            await trade_manager.stop()
        asyncio.run(_test())

    def test_exit_closes_trade(self, db, event_bus, state_manager, trade_manager, classifier):
        async def _test():
            await trade_manager.start()

            parsed = classifier.classify("BUY GOLD\n3340\nSL 3334", telegram_message_id=6)
            await state_manager.handle_new_message(parsed)
            await asyncio.sleep(0.05)

            signal = db.query(Signal).filter(Signal.telegram_message_id == 6).first()
            trade = db.query(Trade).filter(Trade.signal_id == signal.id).first()
            trade.status = "open"
            trade.mt5_ticket = 222222
            db.commit()

            parsed_exit = classifier.classify("EXIT NOW", telegram_message_id=7)
            await state_manager.handle_new_message(parsed_exit)
            await asyncio.sleep(0.05)

            db.refresh(trade)
            assert trade.status == "closed"

            await trade_manager.stop()
        asyncio.run(_test())

    def test_no_duplicate_trades(self, db, event_bus, state_manager, trade_manager, classifier):
        async def _test():
            await trade_manager.start()

            parsed = classifier.classify("BUY GOLD\n3340\nSL 3334", telegram_message_id=8)
            await state_manager.handle_new_message(parsed)
            await asyncio.sleep(0.05)

            # Duplicate same message
            await state_manager.handle_new_message(parsed)
            await asyncio.sleep(0.05)

            signal = db.query(Signal).filter(Signal.telegram_message_id == 8).first()
            trades = db.query(Trade).filter(Trade.signal_id == signal.id).all()
            assert len(trades) == 1

            await trade_manager.stop()
        asyncio.run(_test())

    def test_telegram_edit_updates_and_opens(self, db, event_bus, state_manager, trade_manager, classifier):
        async def _test():
            await trade_manager.start()

            # Initial incomplete signal
            parsed = classifier.classify("BUY GOLD\n3340", telegram_message_id=9)
            await state_manager.handle_new_message(parsed)
            await asyncio.sleep(0.05)

            signal = state_manager.get_signal_by_telegram_id(9)
            assert signal.version == 1
            assert signal.stop_loss is None
            assert db.query(Trade).filter(Trade.signal_id == signal.id).first() is None

            # Provider edits the same message adding SL and TP
            parsed_edit = classifier.classify(
                "BUY GOLD\n3340\nSL 3334\nTP1 3350", telegram_message_id=9
            )
            await state_manager.handle_edit(parsed_edit, signal)
            await asyncio.sleep(0.05)

            signal = state_manager.get_signal_by_telegram_id(9)
            assert signal.version == 2
            assert signal.stop_loss == 3334.0

            trade = db.query(Trade).filter(Trade.signal_id == signal.id).first()
            assert trade is not None
            assert trade.status in ("open", "pending")

            await trade_manager.stop()
        asyncio.run(_test())

    def test_cancel_signal_cancels_pending(self, db, event_bus, state_manager, trade_manager, classifier):
        async def _test():
            await trade_manager.start()

            parsed = classifier.classify(
                "SELL EURUSD\n1.0860\nSL 1.0870", telegram_message_id=10
            )
            await state_manager.handle_new_message(parsed)
            await asyncio.sleep(0.05)

            signal = db.query(Signal).filter(Signal.telegram_message_id == 10).first()
            trade = db.query(Trade).filter(Trade.signal_id == signal.id).first()
            trade.status = "pending"
            trade.mt5_order_ticket = 111111
            db.commit()

            parsed_cancel = classifier.classify("CANCEL", telegram_message_id=11)
            await state_manager.handle_new_message(parsed_cancel)
            await asyncio.sleep(0.05)

            db.refresh(trade)
            assert trade.status == "cancelled"

            await trade_manager.stop()
        asyncio.run(_test())
