"""Shared MT5 mock for all tests."""
from unittest.mock import MagicMock
import sys

# Create shared MT5 mock BEFORE any test module imports project code
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
mt5_mock.ORDER_FILLING_RETURN = 2
mt5_mock.ACCOUNT_TRADE_MODE_DEMO = 0
mt5_mock.ACCOUNT_TRADE_MODE_CONTEST = 1
mt5_mock.ACCOUNT_TRADE_MODE_REAL = 2

sys.modules["MetaTrader5"] = mt5_mock
