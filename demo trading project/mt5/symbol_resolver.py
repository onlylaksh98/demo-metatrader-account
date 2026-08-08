"""Resolves trading symbol aliases to MT5 symbol names."""
import os
import json
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

DEFAULT_ALIASES = {
    "GOLD": "XAUUSD",
    "XAU": "XAUUSD",
    "SILVER": "XAGUSD",
    "XAG": "XAGUSD",
    "GU": "GBPUSD",
    "EU": "EURUSD",
    "UJ": "USDJPY",
    "GJ": "GBPJPY",
    "AU": "AUDUSD",
    "NU": "NZDUSD",
    "UC": "USDCAD",
    "BTC": "BTCUSD",
    "ETH": "ETHUSD",
    "NAS100": "US100",
    "US30": "US30",
    "SPX500": "US500",
}

# Allow override via env var JSON
_aliases_env = os.getenv("SYMBOL_ALIASES", "")
if _aliases_env:
    try:
        DEFAULT_ALIASES.update(json.loads(_aliases_env))
    except json.JSONDecodeError:
        logger.warning("SYMBOL_ALIASES env var is not valid JSON, using defaults")


class SymbolResolver:
    """Maps common VIP-channel aliases to broker-specific MT5 symbols."""

    def __init__(self, aliases: dict | None = None):
        self.aliases = aliases or DEFAULT_ALIASES.copy()
        logger.info(f"SymbolResolver loaded with {len(self.aliases)} aliases")

    def resolve(self, symbol: str) -> str:
        """Resolve an alias to the MT5 symbol name."""
        upper = symbol.upper().strip()
        resolved = self.aliases.get(upper, upper)
        if resolved != upper:
            logger.info(f"Resolved symbol alias: {upper} -> {resolved}")
        return resolved

    def add_alias(self, alias: str, mt5_symbol: str):
        """Runtime alias registration."""
        self.aliases[alias.upper().strip()] = mt5_symbol.upper().strip()
        logger.info(f"Added alias: {alias} -> {mt5_symbol}")
