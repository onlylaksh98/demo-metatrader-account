"""Unit tests for the Signal Intelligence Engine."""
import os
import sys
import asyncio
from datetime import datetime

# Force in-memory DB before any project imports
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from database.models import init_db, SessionLocal, Signal as SignalDB, SignalVersion, SignalEvent
from signal_engine.classifier import SignalClassifier, MessageCategory
from signal_engine.state_manager import SignalStateManager
from signal_engine.models import SignalStatus
from signal_engine.message_router import MessageRouter


@pytest.fixture(scope="function")
def db():
    init_db()
    yield SessionLocal()


@pytest.fixture
def classifier():
    return SignalClassifier()


@pytest.fixture
def state_manager(db):
    sm = SignalStateManager()
    sm.session = db
    return sm


class TestNewSignal:
    def test_full_signal(self, classifier):
        text = """BUY GOLD
3340-3342
SL 3334
TP1 3350
TP2 3360"""
        parsed = classifier.classify(text, telegram_message_id=1)
        assert parsed.category == MessageCategory.NEW_SIGNAL
        assert parsed.symbol == "XAUUSD"
        assert parsed.direction == "BUY"
        assert parsed.entry_min == 3340.0
        assert parsed.entry_max == 3342.0
        assert parsed.stop_loss == 3334.0
        assert len(parsed.take_profits) == 2
        assert parsed.take_profits[0].price == 3350.0
        assert parsed.take_profits[1].price == 3360.0

    def test_signal_without_tp(self, classifier):
        text = "BUY GOLD\n3340"
        parsed = classifier.classify(text, telegram_message_id=2)
        assert parsed.category == MessageCategory.NEW_SIGNAL
        assert parsed.symbol == "XAUUSD"
        assert parsed.direction == "BUY"
        assert parsed.entry_min == 3340.0
        assert parsed.stop_loss is None
        assert len(parsed.take_profits) == 0

    def test_signal_without_sl(self, classifier):
        text = "SELL EURUSD\n1.0850\nTP1 1.0800"
        parsed = classifier.classify(text, telegram_message_id=3)
        assert parsed.category == MessageCategory.NEW_SIGNAL
        assert parsed.symbol == "EURUSD"
        assert parsed.direction == "SELL"
        assert parsed.stop_loss is None
        assert len(parsed.take_profits) == 1


class TestUpdates:
    def test_add_sl_later(self, state_manager, classifier):
        parsed = classifier.classify("BUY GOLD\n3340", telegram_message_id=10)
        asyncio.run(state_manager.handle_new_message(parsed))

        signal = state_manager.get_latest_active_signal("XAUUSD")
        assert signal.stop_loss is None

        parsed_sl = classifier.classify("SL 3334", telegram_message_id=11)
        asyncio.run(state_manager.handle_new_message(parsed_sl))

        signal = state_manager.get_latest_active_signal("XAUUSD")
        assert signal.stop_loss == 3334.0

    def test_add_tp_later(self, state_manager, classifier):
        parsed = classifier.classify("BUY GOLD\n3340", telegram_message_id=20)
        asyncio.run(state_manager.handle_new_message(parsed))

        parsed_tp = classifier.classify("TP 3360", telegram_message_id=21)
        asyncio.run(state_manager.handle_new_message(parsed_tp))

        signal = state_manager.get_latest_active_signal("XAUUSD")
        assert len(signal.take_profits) == 1
        assert signal.take_profits[0].price == 3360.0


class TestEdits:
    def test_telegram_message_edit(self, state_manager, classifier):
        parsed = classifier.classify("BUY GOLD\n3340", telegram_message_id=30)
        asyncio.run(state_manager.handle_new_message(parsed))

        signal = state_manager.get_signal_by_telegram_id(30)
        assert signal.version == 1
        assert signal.stop_loss is None

        parsed_edit = classifier.classify(
            "BUY GOLD\n3340\nSL 3334\nTP1 3350", telegram_message_id=30
        )
        asyncio.run(state_manager.handle_edit(parsed_edit, signal))

        signal = state_manager.get_signal_by_telegram_id(30)
        assert signal.version == 2
        assert signal.stop_loss == 3334.0
        assert len(signal.take_profits) == 1

        versions = (
            state_manager.session.query(SignalVersion)
            .filter(SignalVersion.signal_id == signal.id)
            .all()
        )
        assert len(versions) >= 1


class TestCommands:
    def test_move_sl(self, state_manager, classifier):
        parsed = classifier.classify("BUY GOLD\n3340\nSL 3334", telegram_message_id=40)
        asyncio.run(state_manager.handle_new_message(parsed))

        parsed_move = classifier.classify("MOVE SL TO ENTRY", telegram_message_id=41)
        asyncio.run(state_manager.handle_new_message(parsed_move))

        signal = state_manager.get_latest_active_signal("XAUUSD")
        assert signal.stop_loss == 3340.0

        events = state_manager.get_events(signal.id)
        assert any(e.event_type == "move_stop_loss" for e in events)

    def test_book_profit(self, state_manager, classifier):
        parsed = classifier.classify(
            "BUY GOLD\n3340\nSL 3334\nTP1 3350", telegram_message_id=50
        )
        asyncio.run(state_manager.handle_new_message(parsed))

        signal = state_manager.get_signal_by_telegram_id(50)
        signal.status = SignalStatus.OPEN.value
        state_manager.session.commit()

        parsed_book = classifier.classify("BOOK PROFIT", telegram_message_id=51)
        asyncio.run(state_manager.handle_new_message(parsed_book))

        signal = state_manager.get_signal_by_telegram_id(50)
        assert signal.status == SignalStatus.CLOSED.value

    def test_exit(self, state_manager, classifier):
        parsed = classifier.classify("BUY GOLD\n3340\nSL 3334", telegram_message_id=60)
        asyncio.run(state_manager.handle_new_message(parsed))

        signal = state_manager.get_signal_by_telegram_id(60)
        signal.status = SignalStatus.OPEN.value
        state_manager.session.commit()

        parsed_exit = classifier.classify("EXIT NOW", telegram_message_id=61)
        asyncio.run(state_manager.handle_new_message(parsed_exit))

        signal = state_manager.get_signal_by_telegram_id(60)
        assert signal.status == SignalStatus.CLOSED.value

    def test_partial_close(self, state_manager, classifier):
        parsed = classifier.classify(
            "BUY GOLD\n3340\nSL 3334\nTP1 3350", telegram_message_id=70
        )
        asyncio.run(state_manager.handle_new_message(parsed))

        signal = state_manager.get_latest_active_signal("XAUUSD")
        signal.status = SignalStatus.OPEN.value
        state_manager.session.commit()

        parsed_partial = classifier.classify("BOOK 50%", telegram_message_id=71)
        asyncio.run(state_manager.handle_new_message(parsed_partial))

        signal = state_manager.get_latest_active_signal("XAUUSD")
        assert signal.status == SignalStatus.PARTIAL.value


class TestDuplicates:
    def test_duplicate_message_ignored(self, state_manager, classifier):
        parsed = classifier.classify("BUY GOLD\n3340", telegram_message_id=80)
        asyncio.run(state_manager.handle_new_message(parsed))

        router = MessageRouter(state_manager)
        asyncio.run(router.route("BUY GOLD\n3340", telegram_message_id=80, edited=False))

        signals = (
            state_manager.session.query(SignalDB)
            .filter(SignalDB.telegram_message_id == 80)
            .all()
        )
        assert len(signals) == 1
