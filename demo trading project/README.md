# Telegram2MT5

MVP to automatically test a Telegram VIP trading channel using an MT5 Demo account.

## Setup

1. **Get Telegram API credentials**
   - Go to https://my.telegram.org/apps
   - Create an app and copy `api_id` and `api_hash`

2. **Configure environment**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and fill in:
   - `API_ID` — your Telegram API ID
   - `API_HASH` — your Telegram API hash
   - `PHONE` — your phone number with country code (e.g. `+14155551234`)
   - `CHANNEL_ID` — the target channel (username like `@mychannel` or numeric ID)

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the listener**
   ```bash
   python main.py
   ```
   On first run you will be prompted to enter the Telegram login code sent to your phone.
   The session is saved locally — you won't need to log in again.

5. **Stop**
   Press `Ctrl+C` to stop the listener gracefully.

## Project Structure

- `telegram/client.py` — Telethon client wrapper with auto-login
- `telegram/listener.py` — Channel listener (new + edited messages)
- `telegram/handlers.py` — Message handlers (print, deduplicate, save to DB)
- `parser/` — Signal text parser (not yet implemented)
- `mt5/` — MetaTrader 5 connector (not yet implemented)
- `risk/` — Risk management / position sizing (not yet implemented)
- `database/models.py` — SQLAlchemy models + SQLite setup
- `main.py` — Entry point

## Status

- Telegram listening: **Implemented**
- Signal parsing: **Not implemented**
- MT5 execution: **Not implemented**
