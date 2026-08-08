"""Internal domain models for the Signal Intelligence Engine."""
from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum


class SignalStatus(Enum):
    PENDING = "PENDING"
    WAITING_ENTRY = "WAITING_ENTRY"
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class MessageCategory(Enum):
    NEW_SIGNAL = "new_signal"
    EDIT_SIGNAL = "edit_signal"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    UPDATE_SL = "update_sl"
    UPDATE_TP = "update_tp"
    MOVE_SL = "move_sl"
    BOOK_PROFIT = "book_profit"
    PARTIAL_CLOSE = "partial_close"
    EXIT = "exit"
    CANCEL_SIGNAL = "cancel_signal"
    UNKNOWN = "unknown"


@dataclass
class TakeProfitLevel:
    level: int
    price: float
    hit: bool = False


@dataclass
class ParsedSignal:
    category: MessageCategory
    symbol: Optional[str] = None
    direction: Optional[str] = None
    entry_min: Optional[float] = None
    entry_max: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profits: List[TakeProfitLevel] = field(default_factory=list)
    move_sl_to: Optional[str] = None
    partial_percent: Optional[float] = None
    raw_text: str = ""
    telegram_message_id: Optional[int] = None
