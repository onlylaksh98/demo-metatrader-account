"""Simulation script: replays sample Telegram messages and prints state transitions."""
import os
import sys
import asyncio
from datetime import datetime

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from unittest.mock import MagicMock

# ------------------------------------------------------------------
# Mock MT5 before any project imports
# ------------------------------------------------------------------
mt5_mock = MagicMock()
mt5_mock.initialize.return_value = True
mt5_mock.login.return_value = True
mt5_mock.last_error.return_value = (0, "OK")
mt5_mock.ORDER_TYPE_BUY = 0
mt5_mock.ORDER_TYPE_SELL = 1
mt5_mock.ORDER_TYPE_BUY_LIMIT = 2
mt5_mock.ORDER_TYPE_SELL_LIMIT = 3
mt5_mock.ORDER_TYPE_BUY_STOP = 4
mt5_mock.ORDER_TYPE_SELL_STOP = 5
mt5_mock.TRADE_ACTION_DEAL = 1
mt5_mock.TRADE_ACTION_PENDING = 5
mt5_mock.TRADE_ACTION_SLTP = 6
mt5_mock.TRADE_ACTION_REMOVE = 3
mt5_mock.ORDER_TIME_GTC = 0
mt5_mock.ORDER_FILLING_IOC = 1
mt5_mock.ACCOUNT_TRADE_MODE_DEMO = 0
mt5_mock.ACCOUNT_TRADE_MODE_CONTEST = 1
mt5_mock.ACCOUNT_TRADE_MODE_REAL = 2

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

sys.modules["MetaTrader5"] = mt5_mock

# ------------------------------------------------------------------
# Project imports
# ------------------------------------------------------------------
from database.models import init_db, SessionLocal, Signal, Trade
from signal_engine.events import EventBus
from signal_engine.classifier import SignalClassifier
from mt5.trade_manager import TradeManager
from telegram.handlers import setup_engine


SAMPLE_MESSAGES = [
    # 1. Incomplete signal (no SL) — should wait
    {"id": 1001, "text": "BUY GOLD\n3340-3342", "edited": False},
    # 2. Add SL — signal now complete, trade should open
    {"id": 1002, "text": "SL 3334", "edited": False},
    # 3. Add TP
    {"id": 1003, "text": "TP1 3350", "edited": False},
    # 4. Move SL to entry
    {"id": 1004, "text": "MOVE SL TO ENTRY", "edited": False},
    # 5. Partial close
    {"id": 1005, "text": "BOOK 50%", "edited": False},
    # 6. Full exit
    {"id": 1006, "text": "EXIT NOW", "edited": False},
    # 7. Complete signal immediately
    {"id": 1007, "text": "SELL EURUSD\n1.0850\nSL 1.0860\nTP1 1.0830", "edited": False},
    # 8. Cancel it
    {"id": 1008, "text": "CANCEL", "edited": False},
    # 9. Provider edits original message 1001
    {"id": 1001, "text": "BUY GOLD\n3340-3342\nSL 3330\nTP1 3360", "edited": True},
]


async def run_simulation():
    print("=" * 60)
    print("Telegram2MT5 — Event-Driven Simulation")
    print("=" * 60)

    init_db()
    db = SessionLocal()

    event_bus = EventBus()
    state_manager = setup_engine(event_bus=event_bus)

    trade_manager = TradeManager()
    trade_manager.subscribe(event_bus)
    await trade_manager.start()

    classifier = SignalClassifier()

    print("\n--- Replaying messages ---\n")

    for msg in SAMPLE_MESSAGES:
        print(f"[TELEGRAM] msg_id={msg['id']} edited={msg['edited']}")
        print(f"  Text: {msg['text']!r}")

        parsed = classifier.classify(msg["text"], telegram_message_id=msg["id"])
        print(f"  → Classified as: {parsed.category.value}")

        if msg["edited"]:
            existing = state_manager.get_signal_by_telegram_id(msg["id"])
            if existing:
                await state_manager.handle_edit(parsed, existing)
            else:
                print("  → No existing signal to edit")
        else:
            await state_manager.handle_new_message(parsed)

        # Allow event bus to process
        await asyncio.sleep(0.05)

        # Print current state
        signal = state_manager.get_signal_by_telegram_id(msg["id"])
        if signal:
            tps = [tp.price for tp in signal.take_profits]
            print(
                f"  → Signal state: id={signal.id} status={signal.status} "
                f"entry={signal.entry_min}-{signal.entry_max} SL={signal.stop_loss} TPs={tps}"
            )

        trade = db.query(Trade).filter(Trade.signal_id == (signal.id if signal else -1)).first()
        if trade:
            print(
                f"  → Trade state:  id={trade.id} status={trade.status} "
                f"ticket={trade.mt5_ticket or trade.mt5_order_ticket} volume={trade.volume}"
            )
        elif signal and signal.status not in ("CLOSED", "CANCELLED"):
            print(f"  → Trade state:  waiting for signal completeness")

        print()

    print("=" * 60)
    print("Simulation complete — Summary")
    print("=" * 60)

    signals = db.query(Signal).all()
    trades = db.query(Trade).all()
    print(f"Total signals created: {len(signals)}")
    print(f"Total trades executed: {len(trades)}")
    for t in trades:
        print(
            f"  Trade {t.id}: {t.symbol} {t.action} | "
            f"status={t.status} | vol={t.volume} | entry={t.entry_price} | "
            f"SL={t.stop_loss} | TP={t.take_profit}"
        )

    await trade_manager.stop()


if __name__ == "__main__":
    asyncio.run(run_simulation())
