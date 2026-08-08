"""Classifies raw Telegram text into structured signal categories."""
import re
from typing import Optional, List
from loguru import logger

from signal_engine.models import MessageCategory, ParsedSignal, TakeProfitLevel


class SignalClassifier:
    """Parses VIP channel messages into structured signal data."""

    def __init__(self):
        self.direction_pattern = re.compile(r'\b(BUY|SELL|LONG|SHORT)\b', re.IGNORECASE)
        self.symbol_pattern = re.compile(
            r'\b(GOLD|XAUUSD|XAU/USD|SILVER|XAGUSD|XAG/USD|'
            r'EURUSD|EUR/USD|GBPUSD|GBP/USD|USDJPY|USD/JPY|'
            r'AUDUSD|USD/CAD|USDCAD|NZDUSD|USD/CHF|'
            r'BTC|BTCUSD|ETH|ETHUSD|[A-Z]{3,6})\b',
            re.IGNORECASE,
        )
        self.entry_range_pattern = re.compile(r'(\d+\.?\d*)\s*[-–—]\s*(\d+\.?\d*)')
        self.sl_pattern = re.compile(r'(?:SL|STOP\s*LOSS)\s*[:@]?\s*(\d+\.?\d*)', re.IGNORECASE)
        self.tp_pattern = re.compile(
            r'(?:TP|TAKE\s*PROFIT)(?:(\d)\s*[:@]?\s*|\s+[:@]?\s*)(\d+\.?\d*)',
            re.IGNORECASE,
        )
        self.move_sl_pattern = re.compile(
            r'MOVE\s+SL\s+(?:TO\s+)?(ENTRY|BREAKEVEN|BE|\d+\.?\d*)',
            re.IGNORECASE,
        )
        self.book_profit_pattern = re.compile(
            r'BOOK\s+(?:PROFIT|(\d+)%|(\d+\.?\d*))',
            re.IGNORECASE,
        )
        self.partial_pattern = re.compile(r'(?:PARTIAL|CLOSE)\s+(\d+)%', re.IGNORECASE)
        self.exit_pattern = re.compile(
            r'\b(EXIT\s+NOW|CLOSE\s+NOW|CLOSE\s+ALL|CLOSE\s+TRADE|EXIT)\b',
            re.IGNORECASE,
        )
        self.cancel_pattern = re.compile(r'\b(CANCEL|DELETE|INVALID|REMOVE)\b', re.IGNORECASE)
        self._direction_words = {
            "BUY", "SELL", "LONG", "SHORT", "SL", "TP", "STOP", "LOSS",
            "TAKE", "PROFIT", "ENTRY", "BE", "NOW", "ALL", "TRADE",
            "BOOK", "MOVE", "PARTIAL", "CLOSE", "CANCEL", "DELETE",
            "INVALID", "REMOVE", "AT", "PRICE",
        }

    def classify(self, text: str, telegram_message_id: Optional[int] = None) -> ParsedSignal:
        """Classify raw text into a ParsedSignal."""
        text_stripped = text.strip()
        text_upper = text_stripped.upper()

        # 1. Exit / Close
        if self.exit_pattern.search(text_upper):
            return ParsedSignal(
                category=MessageCategory.EXIT,
                raw_text=text_stripped,
                telegram_message_id=telegram_message_id,
            )

        # 2. Cancel
        if self.cancel_pattern.search(text_upper):
            return ParsedSignal(
                category=MessageCategory.CANCEL_SIGNAL,
                raw_text=text_stripped,
                telegram_message_id=telegram_message_id,
            )

        # 3. Book Profit / Partial Close
        book_match = self.book_profit_pattern.search(text_upper)
        if book_match:
            percent = None
            if book_match.group(1):
                percent = float(book_match.group(1))
            elif book_match.group(2):
                percent = float(book_match.group(2))
            return ParsedSignal(
                category=MessageCategory.BOOK_PROFIT,
                partial_percent=percent,
                raw_text=text_stripped,
                telegram_message_id=telegram_message_id,
            )

        partial_match = self.partial_pattern.search(text_upper)
        if partial_match:
            return ParsedSignal(
                category=MessageCategory.PARTIAL_CLOSE,
                partial_percent=float(partial_match.group(1)),
                raw_text=text_stripped,
                telegram_message_id=telegram_message_id,
            )

        # 4. Move SL
        move_sl_match = self.move_sl_pattern.search(text_upper)
        if move_sl_match:
            target = move_sl_match.group(1).upper()
            return ParsedSignal(
                category=MessageCategory.MOVE_SL,
                move_sl_to=target,
                raw_text=text_stripped,
                telegram_message_id=telegram_message_id,
            )

        # 5. Direction & Symbol detection
        direction_match = self.direction_pattern.search(text_upper)
        symbol_match = self._find_symbol(text_upper)
        has_direction = direction_match is not None
        has_symbol = symbol_match is not None

        sl_match = self.sl_pattern.search(text_upper)
        tp_matches = self.tp_pattern.findall(text_upper)

        # 6. Full new signal
        if has_direction and has_symbol:
            direction = direction_match.group(1).upper()
            symbol = self._normalize_symbol(symbol_match.upper())
            entry_min, entry_max = self._extract_entry(text_stripped)
            sl = self._extract_sl(text_stripped)
            tps = self._extract_tps(text_stripped)
            return ParsedSignal(
                category=MessageCategory.NEW_SIGNAL,
                symbol=symbol,
                direction=direction,
                entry_min=entry_min,
                entry_max=entry_max,
                stop_loss=sl,
                take_profits=tps,
                raw_text=text_stripped,
                telegram_message_id=telegram_message_id,
            )

        # 7. Standalone SL update
        if sl_match and not has_direction and not has_symbol and not tp_matches:
            return ParsedSignal(
                category=MessageCategory.UPDATE_SL,
                stop_loss=float(sl_match.group(1)),
                raw_text=text_stripped,
                telegram_message_id=telegram_message_id,
            )

        # 8. Standalone TP update
        if tp_matches and not has_direction and not has_symbol:
            tps = self._extract_tps(text_stripped)
            return ParsedSignal(
                category=MessageCategory.UPDATE_TP,
                take_profits=tps,
                raw_text=text_stripped,
                telegram_message_id=telegram_message_id,
            )

        # 9. Combined SL+TP update without direction/symbol
        if (sl_match or tp_matches) and not has_direction and not has_symbol:
            sl = self._extract_sl(text_stripped)
            tps = self._extract_tps(text_stripped)
            if sl is not None and tps:
                return ParsedSignal(
                    category=MessageCategory.UPDATE_SL,
                    stop_loss=sl,
                    take_profits=tps,
                    raw_text=text_stripped,
                    telegram_message_id=telegram_message_id,
                )
            elif sl is not None:
                return ParsedSignal(
                    category=MessageCategory.UPDATE_SL,
                    stop_loss=sl,
                    raw_text=text_stripped,
                    telegram_message_id=telegram_message_id,
                )
            elif tps:
                return ParsedSignal(
                    category=MessageCategory.UPDATE_TP,
                    take_profits=tps,
                    raw_text=text_stripped,
                    telegram_message_id=telegram_message_id,
                )

        return ParsedSignal(
            category=MessageCategory.UNKNOWN,
            raw_text=text_stripped,
            telegram_message_id=telegram_message_id,
        )

    def _find_symbol(self, text: str) -> Optional[str]:
        for match in self.symbol_pattern.finditer(text):
            sym = match.group(1).upper()
            if sym not in self._direction_words:
                return sym
        return None

    def _normalize_symbol(self, symbol: str) -> str:
        mapping = {
            "GOLD": "XAUUSD",
            "XAU/USD": "XAUUSD",
            "SILVER": "XAGUSD",
            "XAG/USD": "XAGUSD",
            "EUR/USD": "EURUSD",
            "GBP/USD": "GBPUSD",
            "USD/JPY": "USDJPY",
            "AUD/USD": "AUDUSD",
            "USD/CAD": "USDCAD",
            "NZD/USD": "NZDUSD",
            "USD/CHF": "USDCHF",
        }
        return mapping.get(symbol, symbol)

    def _extract_entry(self, text: str) -> tuple[Optional[float], Optional[float]]:
        range_match = self.entry_range_pattern.search(text)
        if range_match:
            return float(range_match.group(1)), float(range_match.group(2))

        for line in text.split("\n"):
            if re.search(r'\b(SL|TP|STOP|TAKE)\b', line, re.IGNORECASE):
                continue
            match = re.search(r'(\d+\.?\d*)', line)
            if match:
                return float(match.group(1)), None
        return None, None

    def _extract_sl(self, text: str) -> Optional[float]:
        match = self.sl_pattern.search(text)
        if match:
            return float(match.group(1))
        return None

    def _extract_tps(self, text: str) -> List[TakeProfitLevel]:
        matches = self.tp_pattern.findall(text)
        tps = []
        for i, match in enumerate(matches):
            level_str = match[0]
            level = int(level_str) if level_str else i + 1
            price = float(match[1])
            tps.append(TakeProfitLevel(level=level, price=price))
        return tps
