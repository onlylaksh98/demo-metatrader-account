"""Automatic lot-size calculation based on fixed USD risk."""
import MetaTrader5 as mt5
from loguru import logger


class LotCalculator:
    """Calculates lot size so that exactly RISK_USD is at risk per trade."""

    RISK_USD = 60.0

    def calculate(self, symbol: str, entry: float, stop_loss: float) -> float:
        """Return lot size rounded to broker volume step."""
        info = mt5.symbol_info(symbol)
        if info is None:
            raise ValueError(f"Symbol {symbol} not found in MT5")

        tick_size = info.trade_tick_size
        tick_value = info.trade_tick_value
        volume_min = info.volume_min
        volume_max = info.volume_max
        volume_step = info.volume_step

        if tick_size <= 0 or tick_value <= 0:
            raise ValueError(f"Invalid tick data for {symbol}: tick_size={tick_size}, tick_value={tick_value}")

        price_distance = abs(entry - stop_loss)
        ticks = price_distance / tick_size
        loss_per_lot = ticks * tick_value

        if loss_per_lot <= 0:
            raise ValueError(f"Loss per lot calculation invalid: {loss_per_lot}")

        lot = self.RISK_USD / loss_per_lot
        lot = round(lot / volume_step) * volume_step
        lot = max(volume_min, min(lot, volume_max))

        actual_risk = lot * loss_per_lot
        logger.info(
            f"Lot calc for {symbol}: entry={entry}, SL={stop_loss}, "
            f"distance={price_distance}, lot={lot}, risk=${actual_risk:.2f}"
        )
        return lot
