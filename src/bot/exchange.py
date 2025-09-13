from __future__ import annotations

import ccxt
import time
from typing import Any, Dict, List, Optional

from .formatting import build_market_info, normalize_price, normalize_amount


class BybitExchange:
    def __init__(self, api_key: Optional[str], api_secret: Optional[str], testnet: bool):
        opts = {
            "apiKey": api_key or "",
            "secret": api_secret or "",
            "enableRateLimit": True,
            "options": {"defaultType": "swap"},
        }
        self.client = ccxt.bybit(opts)
        self.client.setSandboxMode(bool(testnet))
        self.markets = None
        self.market = None

    def init(self, symbol: str, margin_mode: str, leverage: int):
        self.markets = self.client.load_markets()
        if symbol not in self.markets:
            raise RuntimeError(f"Symbol {symbol} not found in markets")
        market = self.markets[symbol]
        if not market.get("contract", False) or not market.get("linear", False):
            raise RuntimeError("Symbol is not a linear perpetual contract")
        self.market = market

        # Try to set margin mode and leverage
        try:
            if hasattr(self.client, "setMarginMode"):
                self.client.setMarginMode(margin_mode, symbol)
        except Exception as e:
            # Not all accounts/symbols allow switching; log-friendly raise later or ignore
            pass
        try:
            if hasattr(self.client, "setLeverage"):
                self.client.setLeverage(leverage, symbol)
        except Exception:
            pass

    def get_market_info(self):
        return build_market_info(self.market)

    # Snapshots
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 200):
        return self.client.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    def fetch_balance(self):
        return self.client.fetch_balance()

    def fetch_positions(self, symbols: Optional[List[str]] = None):
        # ccxt unified
        return self.client.fetch_positions(symbols)

    def fetch_open_orders(self, symbol: str):
        return self.client.fetch_open_orders(symbol)

    def fetch_ticker(self, symbol: str):
        return self.client.fetch_ticker(symbol)

    def fetch_order_book(self, symbol: str, limit: int = 5):
        return self.client.fetch_order_book(symbol, limit=limit)

    def fetch_trades(self, symbol: str, limit: int = 200):
        try:
            return self.client.fetch_trades(symbol, limit=limit)
        except Exception:
            return []

    def fetch_funding_rate(self, symbol: str):
        try:
            if hasattr(self.client, 'fetch_funding_rate'):
                return self.client.fetch_funding_rate(symbol)
        except Exception:
            return None
        return None

    def fetch_open_interest(self, symbol: str):
        try:
            if hasattr(self.client, 'fetch_open_interest'):
                return self.client.fetch_open_interest(symbol)
        except Exception:
            return None
        return None

    # Actions
    def create_limit_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float,
        *,
        client_order_id: Optional[str] = None,
        time_in_force: Optional[str] = None,
        reduce_only: Optional[bool] = None,
        post_only: Optional[bool] = None,
        take_profit: Optional[float] = None,
        stop_loss: Optional[float] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if client_order_id:
            params["clientOrderId"] = client_order_id
        if time_in_force:
            params["timeInForce"] = time_in_force
        if reduce_only is not None:
            params["reduceOnly"] = reduce_only
        if post_only is not None:
            params["postOnly"] = post_only
        if take_profit is not None:
            params["takeProfit"] = take_profit
        if stop_loss is not None:
            params["stopLoss"] = stop_loss

        return self.client.create_order(symbol, "limit", side, amount, price, params)

    def cancel_order(self, order_id: str, symbol: str):
        return self.client.cancel_order(order_id, symbol)

    def cancel_all_orders(self, symbol: str):
        return self.client.cancel_all_orders(symbol)

    def normalize_price_amount(self, price: float, amount: float) -> tuple[float, float]:
        mi = self.get_market_info()
        p = normalize_price(price, mi)
        a = normalize_amount(amount, mi)
        return p, a

