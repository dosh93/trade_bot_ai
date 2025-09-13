from __future__ import annotations

from typing import Dict, List, Any, Optional
import math


def _ema(values: List[float], period: int) -> List[Optional[float]]:
    if period <= 1:
        return [float(v) for v in values]
    k = 2 / (period + 1)
    ema: List[Optional[float]] = [None] * len(values)
    s = 0.0
    count = 0
    for i, v in enumerate(values):
        if count < period:
            s += v
            count += 1
            if count == period:
                ema[i] = s / period
        else:
            prev = ema[i - 1] if ema[i - 1] is not None else v
            ema[i] = v * k + prev * (1 - k)
    return ema


def _sma(values: List[float], period: int) -> List[Optional[float]]:
    if period <= 1:
        return [float(v) for v in values]
    out: List[Optional[float]] = [None] * len(values)
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= period:
            s -= values[i - period]
        if i >= period - 1:
            out[i] = s / period
    return out


def _stddev(values: List[float], period: int) -> List[Optional[float]]:
    ma = _sma(values, period)
    out: List[Optional[float]] = [None] * len(values)
    for i in range(len(values)):
        if ma[i] is None:
            continue
        start = i - period + 1
        window = values[start : i + 1]
        m = float(ma[i])
        var = sum((x - m) ** 2 for x in window) / period
        out[i] = math.sqrt(var)
    return out


def _rsi(values: List[float], period: int = 14) -> List[Optional[float]]:
    if len(values) < period + 1:
        return [None] * len(values)
    gains = [0.0]
    losses = [0.0]
    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains[1 : period + 1]) / period
    avg_loss = sum(losses[1 : period + 1]) / period
    rsi: List[Optional[float]] = [None] * len(values)
    rs = (avg_gain / avg_loss) if avg_loss != 0 else float('inf')
    rsi[period] = 100 - (100 / (1 + rs))
    for i in range(period + 1, len(values)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i] = 100 - (100 / (1 + rs))
    return rsi


def _true_range(h: List[float], l: List[float], c: List[float]) -> List[float]:
    tr: List[float] = [h[0] - l[0]]
    for i in range(1, len(h)):
        tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
    return tr


def _atr(h: List[float], l: List[float], c: List[float], period: int = 14) -> List[Optional[float]]:
    tr = _true_range(h, l, c)
    return _ema(tr, period)


def _vwap(h: List[float], l: List[float], c: List[float], v: List[float]) -> List[Optional[float]]:
    out: List[Optional[float]] = []
    cum_v = 0.0
    cum_pv = 0.0
    for i in range(len(c)):
        typical = (h[i] + l[i] + c[i]) / 3
        vol = v[i]
        cum_v += vol
        cum_pv += typical * vol
        if cum_v == 0:
            out.append(None)
        else:
            out.append(cum_pv / cum_v)
    return out


def _volatility(values: List[float], period: int = 30) -> List[Optional[float]]:
    # std dev of simple returns
    if len(values) < period + 1:
        return [None] * len(values)
    rets = [0.0] + [(values[i] - values[i - 1]) / values[i - 1] if values[i - 1] else 0.0 for i in range(1, len(values))]
    return _stddev(rets, period)


def compute_features(ohlcv: List[List[float]]) -> Dict[str, Any]:
    # ohlcv: [ [ts, open, high, low, close, volume], ... ]
    if not ohlcv:
        return {}
    o = [x[1] for x in ohlcv]
    h = [x[2] for x in ohlcv]
    l = [x[3] for x in ohlcv]
    c = [x[4] for x in ohlcv]
    v = [x[5] for x in ohlcv]

    ema20 = _ema(c, 20)
    ema50 = _ema(c, 50)
    ema200 = _ema(c, 200)
    rsi14 = _rsi(c, 14)
    atr14 = _atr(h, l, c, 14)
    bb20 = _sma(c, 20)
    bb20_std = _stddev(c, 20)
    vwap = _vwap(h, l, c, v)
    vol30 = _volatility(c, 30)

    def last_valid(series: List[Optional[float]]) -> Optional[float]:
        for x in reversed(series):
            if x is not None and not math.isnan(x):
                return float(x)
        return None

    return {
        "ema20": last_valid(ema20),
        "ema50": last_valid(ema50),
        "ema200": last_valid(ema200),
        "rsi14": last_valid(rsi14),
        "atr14": last_valid(atr14),
        "bb20_mid": last_valid(bb20),
        "bb20_std": last_valid(bb20_std),
        "vwap": last_valid(vwap),
        "volatility30": last_valid(vol30),
    }

