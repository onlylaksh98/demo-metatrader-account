from loguru import logger
import os


class RiskManager:
    def __init__(self):
        self.risk_percent = float(os.getenv("RISK_PER_TRADE_PERCENT", 1.0))
        logger.info(f"RiskManager initialized with risk {self.risk_percent}% per trade")

    def calculate_volume(self, symbol: str, entry_price: float, stop_loss: float, balance: float) -> float:
        """Calculate lot size based on risk. Placeholder implementation."""
        # TODO: Implement real calculation
        return 0.01
