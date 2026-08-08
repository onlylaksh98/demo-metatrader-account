# Telegram2MT5

Telegram2MT5 is an event-driven Python-based trading automation project designed to process trading signals received from Telegram and connect them with MetaTrader 5 (MT5).

The system listens for new and edited Telegram messages, classifies trading signals, manages signal states through an event bus, stores information using SQLite/SQLAlchemy, and manages trades through an MT5 Trade Manager. The project also includes an event-driven simulation environment for testing signal workflows without requiring a live MT5 connection.

## Key Features

* 📡 Telegram channel message monitoring
* 🔄 Support for new and edited trading signals
* 🧠 Event-driven signal processing
* 💾 SQLite database with SQLAlchemy
* 📈 MetaTrader 5 integration
* ⚙️ Trade management and execution
* 🛡️ Safe MT5 TerminalInfo attribute handling
* 🧪 MT5 verification and simulation scripts
* 📝 Structured logging with Loguru
* 🔐 Environment-based configuration using `.env`

The project uses Telethon, MetaTrader5, SQLAlchemy, python-dotenv, and Loguru.

## Signal Workflow

Telegram message → Signal Classification → Event Bus → Signal State Management → MT5 Trade Manager → Trade Execution

The simulation demonstrates workflows including incomplete signals, SL/TP updates, moving SL to entry, partial closing, full exits, cancellation, and edited Telegram messages.

## MT5 Reliability

The project includes a fix for invalid `TerminalInfo` attribute access by using `_asdict()` with safe `.get()` fallbacks. This prevents crashes caused by unsupported attributes and uses verified MT5 attributes such as `connected`, `trade_allowed`, and `tradeapi_disabled`.

## Testing

A dedicated verification script checks MT5 initialization, login/account information, terminal information, and available symbols.

> **Note:** This repository is an MVP/prototype and should be tested thoroughly on a demo account before any real-money trading.
