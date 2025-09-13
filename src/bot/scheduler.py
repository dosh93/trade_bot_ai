from __future__ import annotations

import time
from datetime import datetime, timezone


TIMEFRAME_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "1d": 86400,
}


def floor_ts_to_timeframe(ts: int | float, timeframe: str) -> int:
    s = TIMEFRAME_SECONDS.get(timeframe)
    if not s:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    return int(ts // s * s)


def next_candle_close_time(timeframe: str, now_ts: float | None = None) -> int:
    now_ts = now_ts or time.time()
    base = floor_ts_to_timeframe(now_ts, timeframe)
    return base + TIMEFRAME_SECONDS[timeframe]


def wait_until(ts: int):
    while True:
        now = time.time()
        if now >= ts:
            return
        time.sleep(min(0.5, max(0.01, ts - now)))


def wait_for_next_closed_candle(timeframe: str):
    close_ts = next_candle_close_time(timeframe)
    wait_until(close_ts)


def last_closed_candle_open_time(timeframe: str, now_ts: float | None = None) -> int:
    now_ts = now_ts or time.time()
    close_ts = next_candle_close_time(timeframe, now_ts)
    return close_ts - TIMEFRAME_SECONDS[timeframe]


