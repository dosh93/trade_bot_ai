from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class RiskLimits:
    max_open_orders: int
    max_position_usdt: float
    max_orders_per_hour: int
    default_tp_pct: float
    default_sl_pct: float
    reduce_only_when_closing: bool


def check_open_orders_limit(current_open_orders: int, limits: RiskLimits) -> bool:
    return current_open_orders < limits.max_open_orders


def check_orders_per_hour(recent_orders_count: int, limits: RiskLimits) -> bool:
    return recent_orders_count < limits.max_orders_per_hour


def would_exceed_position_usdt(current_position_usdt: float, additional_usdt: float, limits: RiskLimits) -> bool:
    return (current_position_usdt + additional_usdt) > limits.max_position_usdt


def default_tp_sl(entry_price: float, side: str, tp_pct: float, sl_pct: float) -> tuple[float, float]:
    # pct are absolute percent (e.g. 0.7 => 0.7%)
    if side == "buy":
        tp = entry_price * (1 + tp_pct / 100)
        sl = entry_price * (1 - sl_pct / 100)
    else:
        tp = entry_price * (1 - tp_pct / 100)
        sl = entry_price * (1 + sl_pct / 100)
    return tp, sl


