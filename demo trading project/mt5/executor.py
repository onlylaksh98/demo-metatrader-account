"""Low-level MT5 order execution."""
import MetaTrader5 as mt5
from loguru import logger

from mt5.symbol_resolver import SymbolResolver
from mt5.lot_calculator import LotCalculator

# MT5 constants
ORDER_TYPE_BUY = mt5.ORDER_TYPE_BUY
ORDER_TYPE_SELL = mt5.ORDER_TYPE_SELL
ORDER_TYPE_BUY_LIMIT = mt5.ORDER_TYPE_BUY_LIMIT
ORDER_TYPE_SELL_LIMIT = mt5.ORDER_TYPE_SELL_LIMIT
ORDER_TYPE_BUY_STOP = mt5.ORDER_TYPE_BUY_STOP
ORDER_TYPE_SELL_STOP = mt5.ORDER_TYPE_SELL_STOP
TRADE_ACTION_DEAL = mt5.TRADE_ACTION_DEAL
TRADE_ACTION_PENDING = mt5.TRADE_ACTION_PENDING
TRADE_ACTION_SLTP = mt5.TRADE_ACTION_SLTP
TRADE_ACTION_REMOVE = mt5.TRADE_ACTION_REMOVE
ORDER_TIME_GTC = mt5.ORDER_TIME_GTC
ORDER_FILLING_IOC = mt5.ORDER_FILLING_IOC
ORDER_FILLING_RETURN = mt5.ORDER_FILLING_RETURN

MAGIC_NUMBER = 123456


class MT5Executor:
    """Sends orders to MT5 and handles responses."""

    def __init__(self, resolver: SymbolResolver, lot_calculator: LotCalculator):
        self.resolver = resolver
        self.lot_calculator = lot_calculator

    # ------------------------------------------------------------------
    # Safety helpers
    # ------------------------------------------------------------------
    def _validate_symbol(self, symbol: str) -> bool:
        resolved = self.resolver.resolve(symbol)
        if not mt5.symbol_select(resolved, True):
            logger.error(f"symbol_select failed for {resolved}")
            return False
        info = mt5.symbol_info(resolved)
        if info is None:
            logger.error(f"symbol_info failed for {resolved}")
            return False
        if not info.visible:
            logger.error(f"Symbol {resolved} is not visible")
            return False
        return True

    def _validate_sl(self, direction: str, entry: float, sl: float) -> bool:
        if direction == "BUY" and sl >= entry:
            logger.error(f"Invalid SL for BUY: SL={sl} >= entry={entry}")
            return False
        if direction == "SELL" and sl <= entry:
            logger.error(f"Invalid SL for SELL: SL={sl} <= entry={entry}")
            return False
        return True

    def _get_current_price(self, symbol: str, direction: str) -> float:
        """Get ask for BUY, bid for SELL."""
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError(f"Failed to get tick for {symbol}")
        return tick.ask if direction == "BUY" else tick.bid

    def _determine_order_type_and_price(
        self, direction: str, entry: float, current_price: float
    ) -> tuple:
        """For single entry price."""
        if direction == "BUY":
            if entry < current_price:
                return ORDER_TYPE_BUY_LIMIT, entry
            elif entry > current_price:
                return ORDER_TYPE_BUY_STOP, entry
            else:
                return ORDER_TYPE_BUY, current_price
        else:
            if entry > current_price:
                return ORDER_TYPE_SELL_LIMIT, entry
            elif entry < current_price:
                return ORDER_TYPE_SELL_STOP, entry
            else:
                return ORDER_TYPE_SELL, current_price

    def _determine_range_order_type_and_price(
        self, direction: str, entry_min: float, entry_max: float, current_price: float
    ) -> tuple:
        """For entry range [min, max]."""
        if direction == "BUY":
            if entry_min <= current_price <= entry_max:
                return ORDER_TYPE_BUY, current_price
            elif current_price < entry_min:
                return ORDER_TYPE_BUY_STOP, entry_min
            else:
                return ORDER_TYPE_BUY_LIMIT, entry_max
        else:
            if entry_min <= current_price <= entry_max:
                return ORDER_TYPE_SELL, current_price
            elif current_price > entry_max:
                return ORDER_TYPE_SELL_STOP, entry_max
            else:
                return ORDER_TYPE_SELL_LIMIT, entry_min

    def _build_request(
        self,
        action: int,
        symbol: str,
        order_type: int,
        volume: float,
        price: float,
        sl: float | None = None,
        tp: float | None = None,
        position: int | None = None,
        order: int | None = None,
    ) -> dict:
        request = {
            "action": action,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "deviation": 10,
            "magic": MAGIC_NUMBER,
            "comment": "T2M5",
            "type_time": ORDER_TIME_GTC,
            "type_filling": ORDER_FILLING_IOC,
        }
        if sl is not None:
            request["sl"] = sl
        if tp is not None:
            request["tp"] = tp
        if position is not None:
            request["position"] = position
        if order is not None:
            request["order"] = order
        return request

    def _send(self, request: dict) -> dict:
        """Send order and log result."""
        logger.info(f"MT5 request: {request}")
        result = mt5.order_send(request)
        if result is None:
            err = mt5.last_error()
            logger.error(f"MT5 order_send returned None, error: {err}")
            raise RuntimeError(f"MT5 order_send failed: {err}")
        logger.info(f"MT5 result: retcode={result.retcode}, ticket={getattr(result, 'order', None) or getattr(result, 'deal', None)}, comment={result.comment}")
        if result.retcode != 10009 and result.retcode != 10008:
            logger.error(f"MT5 order failed: retcode={result.retcode}, comment={result.comment}")
            raise RuntimeError(f"MT5 order failed: {result.retcode} - {result.comment}")
        return result

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def open_position(
        self,
        symbol: str,
        direction: str,
        entry: float | None,
        entry_min: float | None,
        entry_max: float | None,
        stop_loss: float,
        take_profit: float | None,
    ) -> dict:
        """Open a market or pending order. Returns result dict with ticket."""
        resolved = self.resolver.resolve(symbol)
        if not self._validate_symbol(resolved):
            raise RuntimeError(f"Symbol validation failed: {resolved}")

        if not self._validate_sl(direction, entry or entry_min or entry_max, stop_loss):
            raise RuntimeError("SL validation failed")

        current_price = self._get_current_price(resolved, direction)

        # Determine entry price and order type
        if entry_min is not None and entry_max is not None:
            order_type, price = self._determine_range_order_type_and_price(
                direction, entry_min, entry_max, current_price
            )
            entry_for_calc = entry_min if direction == "BUY" else entry_max
        elif entry is not None:
            order_type, price = self._determine_order_type_and_price(direction, entry, current_price)
            entry_for_calc = entry
        else:
            order_type = ORDER_TYPE_BUY if direction == "BUY" else ORDER_TYPE_SELL
            price = current_price
            entry_for_calc = current_price

        lot = self.lot_calculator.calculate(resolved, entry_for_calc, stop_loss)

        if order_type in (ORDER_TYPE_BUY_LIMIT, ORDER_TYPE_SELL_LIMIT, ORDER_TYPE_BUY_STOP, ORDER_TYPE_SELL_STOP):
            action = TRADE_ACTION_PENDING
        else:
            action = TRADE_ACTION_DEAL

        request = self._build_request(
            action=action,
            symbol=resolved,
            order_type=order_type,
            volume=lot,
            price=price,
            sl=stop_loss,
            tp=take_profit,
        )
        result = self._send(request)
        return {
            "result": result,
            "order_type": order_type,
            "price": price,
            "volume": lot,
            "symbol": resolved,
        }

    def modify_sl(self, position_ticket: int, new_sl: float) -> dict:
        """Modify stop-loss on an open position."""
        positions = mt5.positions_get(ticket=position_ticket)
        if not positions:
            raise RuntimeError(f"Position {position_ticket} not found")
        pos = positions[0]
        request = self._build_request(
            action=TRADE_ACTION_SLTP,
            symbol=pos.symbol,
            order_type=pos.type,
            volume=pos.volume,
            price=pos.price_current,
            sl=new_sl,
            tp=pos.tp,
            position=position_ticket,
        )
        return self._send(request)

    def modify_tp(self, position_ticket: int, new_tp: float) -> dict:
        """Modify take-profit on an open position."""
        positions = mt5.positions_get(ticket=position_ticket)
        if not positions:
            raise RuntimeError(f"Position {position_ticket} not found")
        pos = positions[0]
        request = self._build_request(
            action=TRADE_ACTION_SLTP,
            symbol=pos.symbol,
            order_type=pos.type,
            volume=pos.volume,
            price=pos.price_current,
            sl=pos.sl,
            tp=new_tp,
            position=position_ticket,
        )
        return self._send(request)

    def partial_close(self, position_ticket: int, percent: float) -> dict:
        """Close a percentage of an open position."""
        positions = mt5.positions_get(ticket=position_ticket)
        if not positions:
            raise RuntimeError(f"Position {position_ticket} not found")
        pos = positions[0]
        volume_to_close = round((pos.volume * percent / 100) / pos.volume_step) * pos.volume_step
        volume_to_close = max(pos.volume_step, min(volume_to_close, pos.volume))

        close_type = ORDER_TYPE_SELL if pos.type == ORDER_TYPE_BUY else ORDER_TYPE_BUY
        price = self._get_current_price(pos.symbol, "BUY" if close_type == ORDER_TYPE_BUY else "SELL")

        request = self._build_request(
            action=TRADE_ACTION_DEAL,
            symbol=pos.symbol,
            order_type=close_type,
            volume=volume_to_close,
            price=price,
            position=position_ticket,
        )
        result = self._send(request)
        return {"result": result, "closed_volume": volume_to_close}

    def close_position(self, position_ticket: int) -> dict:
        """Close an entire position."""
        positions = mt5.positions_get(ticket=position_ticket)
        if not positions:
            raise RuntimeError(f"Position {position_ticket} not found")
        pos = positions[0]
        close_type = ORDER_TYPE_SELL if pos.type == ORDER_TYPE_BUY else ORDER_TYPE_BUY
        price = self._get_current_price(pos.symbol, "BUY" if close_type == ORDER_TYPE_BUY else "SELL")

        request = self._build_request(
            action=TRADE_ACTION_DEAL,
            symbol=pos.symbol,
            order_type=close_type,
            volume=pos.volume,
            price=price,
            position=position_ticket,
        )
        return self._send(request)

    def cancel_order(self, order_ticket: int) -> dict:
        """Cancel a pending order."""
        request = {
            "action": TRADE_ACTION_REMOVE,
            "order": order_ticket,
        }
        return self._send(request)
