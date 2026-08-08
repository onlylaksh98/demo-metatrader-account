"""Unit tests for the MT5 Execution Engine (with mocked MetaTrader5)."""
import os
import sys
from unittest.mock import MagicMock

# Force in-memory DB
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from tests.conftest import mt5_mock

# ------------------------------------------------------------------
# Configure shared mock for this test module
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
sym_mock.trade_tick_size = 0.00001
sym_mock.trade_tick_value = 1.0
sym_mock.volume_min = 0.01
sym_mock.volume_max = 100.0
sym_mock.volume_step = 0.01
sym_mock.visible = True
mt5_mock.symbol_info.return_value = sym_mock
mt5_mock.symbol_select.return_value = True

tick_mock = MagicMock()
tick_mock.ask = 1.08500
tick_mock.bid = 1.08490
mt5_mock.symbol_info_tick.return_value = tick_mock

order_result = MagicMock()
order_result.retcode = 10009
order_result.order = 123456
order_result.deal = 654321
order_result.comment = "Done"
mt5_mock.order_send.return_value = order_result

pos_mock = MagicMock()
pos_mock.ticket = 654321
pos_mock.symbol = "EURUSD"
pos_mock.type = 0  # BUY
pos_mock.volume = 0.12
pos_mock.volume_step = 0.01
pos_mock.price_current = 1.08500
pos_mock.sl = 1.08400
pos_mock.tp = 1.08600
mt5_mock.positions_get.return_value = (pos_mock,)

# Now import project modules
from database.models import init_db, SessionLocal, Signal, SignalEvent, Trade
from mt5.connection import MT5Connection
from mt5.symbol_resolver import SymbolResolver
from mt5.lot_calculator import LotCalculator
from mt5.executor import MT5Executor
from mt5.trade_manager import TradeManager


@pytest.fixture(autouse=True)
def reset_mock():
    """Reset mock return values before each test."""
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


class TestConnection:
    def test_connect_success(self):
        conn = MT5Connection()
        assert conn.connect() is True
        assert conn.is_demo() is True
        assert conn.is_trading_enabled() is True

    def test_refuse_live_account(self):
        live_acc = MagicMock()
        live_acc.login = 99999
        live_acc.trade_mode = 2  # REAL
        mt5_mock.account_info.return_value = live_acc

        conn = MT5Connection()
        conn.connected = True
        assert conn.is_demo() is False

        mt5_mock.account_info.return_value = acc_mock


class TestSymbolResolver:
    def test_gold_alias(self):
        r = SymbolResolver()
        assert r.resolve("GOLD") == "XAUUSD"

    def test_eu_alias(self):
        r = SymbolResolver()
        assert r.resolve("EU") == "EURUSD"

    def test_no_alias(self):
        r = SymbolResolver()
        assert r.resolve("GBPUSD") == "GBPUSD"

    def test_custom_alias(self):
        r = SymbolResolver(aliases={"OIL": "USOIL"})
        assert r.resolve("OIL") == "USOIL"


class TestLotCalculator:
    def test_lot_size(self):
        calc = LotCalculator()
        lot = calc.calculate("EURUSD", entry=1.08500, stop_loss=1.08400)
        # distance = 0.00100, ticks = 100, tick_value = 1.0, loss_per_lot = 100
        # lot = 60 / 100 = 0.6 -> rounded to step 0.01 -> 0.60
        assert lot == pytest.approx(0.60, abs=0.01)

    def test_lot_size_respects_min(self):
        calc = LotCalculator()
        # Very wide SL -> tiny lot
        sym_mock.trade_tick_value = 10.0
        lot = calc.calculate("EURUSD", entry=1.08500, stop_loss=1.08000)
        assert lot >= sym_mock.volume_min
        sym_mock.trade_tick_value = 1.0


class TestExecutor:
    def test_open_buy_market(self):
        resolver = SymbolResolver()
        calc = LotCalculator()
        exe = MT5Executor(resolver, calc)
        result = exe.open_position(
            symbol="EURUSD",
            direction="BUY",
            entry=1.08500,
            entry_min=None,
            entry_max=None,
            stop_loss=1.08400,
            take_profit=1.08600,
        )
        assert result["result"].retcode == 10009
        assert result["order_type"] == mt5_mock.ORDER_TYPE_BUY

    def test_open_sell_limit(self):
        resolver = SymbolResolver()
        calc = LotCalculator()
        exe = MT5Executor(resolver, calc)
        result = exe.open_position(
            symbol="EURUSD",
            direction="SELL",
            entry=1.08600,
            entry_min=None,
            entry_max=None,
            stop_loss=1.08700,
            take_profit=1.08400,
        )
        assert result["order_type"] == mt5_mock.ORDER_TYPE_SELL_LIMIT

    def test_modify_sl(self):
        resolver = SymbolResolver()
        calc = LotCalculator()
        exe = MT5Executor(resolver, calc)
        result = exe.modify_sl(654321, 1.08350)
        assert result.retcode == 10009

    def test_modify_tp(self):
        resolver = SymbolResolver()
        calc = LotCalculator()
        exe = MT5Executor(resolver, calc)
        result = exe.modify_tp(654321, 1.08700)
        assert result.retcode == 10009

    def test_close_position(self):
        resolver = SymbolResolver()
        calc = LotCalculator()
        exe = MT5Executor(resolver, calc)
        result = exe.close_position(654321)
        assert result.retcode == 10009

    def test_partial_close(self):
        resolver = SymbolResolver()
        calc = LotCalculator()
        exe = MT5Executor(resolver, calc)
        result = exe.partial_close(654321, 50.0)
        assert result["result"].retcode == 10009
        assert result["closed_volume"] == pytest.approx(0.06, abs=0.01)


class TestTradeManager:
    def test_signal_created_opens_trade(self, db):
        tm = TradeManager()
        sig = Signal(
            symbol="EURUSD",
            direction="BUY",
            entry_price=1.08500,
            stop_loss=1.08400,
            status="WAITING_ENTRY",
        )
        db.add(sig)
        db.commit()

        evt = SignalEvent(signal_id=sig.id, event_type="signal_created", payload="{}")
        db.add(evt)
        db.commit()

        import asyncio
        asyncio.run(tm._process_event(evt))

        trade = db.query(Trade).filter(Trade.signal_id == sig.id).first()
        assert trade is not None
        assert trade.action == "BUY"
        assert trade.status in ("open", "pending")

    def test_close_trade_event(self, db):
        tm = TradeManager()
        sig = Signal(symbol="EURUSD", direction="BUY", entry_price=1.08500, stop_loss=1.08400, status="OPEN")
        db.add(sig)
        db.commit()

        trade = Trade(
            signal_id=sig.id,
            symbol="EURUSD",
            action="BUY",
            volume=0.12,
            entry_price=1.08500,
            stop_loss=1.08400,
            mt5_ticket=654321,
            status="open",
        )
        db.add(trade)
        db.commit()

        evt = SignalEvent(signal_id=sig.id, event_type="close_trade", payload="{}")
        db.add(evt)
        db.commit()

        import asyncio
        asyncio.run(tm._process_event(evt))

        db.refresh(trade)
        assert trade.status == "closed"
