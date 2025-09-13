from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import math


@dataclass
class MarketInfo:
    price_step: Optional[float]
    amount_step: Optional[float]
    min_price: Optional[float]
    max_price: Optional[float]
    min_amount: Optional[float]
    max_amount: Optional[float]


def build_market_info(market: dict) -> MarketInfo:
    precision = market.get("precision", {}) or {}
    limits = market.get("limits", {}) or {}
    price_limits = limits.get("price", {}) if isinstance(limits, dict) else {}
    amount_limits = limits.get("amount", {}) if isinstance(limits, dict) else {}

    def to_step(v) -> Optional[float]:
        if v is None:
            return None
        try:
            # ccxt may return step (e.g., 0.01) or number of decimals (e.g., 2)
            if isinstance(v, (int,)):
                # decimals -> step
                return float(10 ** (-int(v)))
            vf = float(v)
            if vf <= 0:
                return None
            if vf < 1:
                return vf
            # if >=1, treat as decimals count (unlikely)
            return float(10 ** (-int(vf)))
        except Exception:
            return None

    return MarketInfo(
        price_step=to_step(precision.get("price")),
        amount_step=to_step(precision.get("amount")),
        min_price=price_limits.get("min"),
        max_price=price_limits.get("max"),
        min_amount=amount_limits.get("min"),
        max_amount=amount_limits.get("max"),
    )


def round_to_step_down(value: float, step: Optional[float]) -> float:
    if step is None or step <= 0:
        return value
    n = math.floor(value / step) * step
    # format to a sensible number of decimals based on step
    try:
        if step >= 1:
            return float(int(n))
        decimals = max(0, int(round(-math.log10(step))))
        return float(f"{n:.{decimals}f}")
    except Exception:
        return n


def clamp(value: float, vmin: Optional[float], vmax: Optional[float]) -> float:
    if vmin is not None and value < vmin:
        value = vmin
    if vmax is not None and value > vmax:
        value = vmax
    return value


def normalize_price(price: float, market: MarketInfo) -> float:
    p = round_to_step_down(price, market.price_step)
    p = clamp(p, market.min_price, market.max_price)
    return p


def normalize_amount(amount: float, market: MarketInfo) -> float:
    a = round_to_step_down(amount, market.amount_step)
    a = clamp(a, market.min_amount, market.max_amount)
    return a
