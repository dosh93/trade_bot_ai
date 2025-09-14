from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional, Any, Dict, List

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.json import JSON
import shortuuid

from .config import load_config, AppConfig
from .exchange import BybitExchange
from .scheduler import wait_for_next_closed_candle, last_closed_candle_open_time
from .chat import ChatClient
from .decisions import Decision
from .state import State
from .risk import RiskLimits, check_open_orders_limit, check_orders_per_hour, would_exceed_position_usdt
from .metrics import start_metrics_server_if_enabled, cycles_total, orders_placed_total, errors_total
from .features import compute_features


app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()


def _load_cfg(path: str | None, overrides: Dict[str, Any]) -> AppConfig:
    cfg = load_config(path)
    # CLI overrides (shallow for common fields)
    ex = cfg.exchange
    if overrides.get("symbol"):
        ex.symbol = overrides["symbol"]
    if overrides.get("timeframe"):
        ex.timeframe = overrides["timeframe"]
    if overrides.get("testnet") is not None:
        ex.testnet = overrides["testnet"]
    if overrides.get("dry_run") is not None:
        cfg.runtime.dry_run = overrides["dry_run"]
    return cfg


def _init_clients(cfg: AppConfig, env_file: Optional[str] = None) -> tuple[BybitExchange, State, Optional[ChatClient]]:
    if env_file:
        load_dotenv(dotenv_path=env_file, override=False)
    else:
        load_dotenv(override=False)
    bybit_key = os.getenv("BYBIT_API_KEY", "")
    bybit_secret = os.getenv("BYBIT_API_SECRET", "")
    openai_key = os.getenv("OPENAI_API_KEY", "")

    ex = BybitExchange(bybit_key, bybit_secret, cfg.exchange.testnet)
    ex.init(cfg.exchange.symbol, cfg.exchange.margin_mode, cfg.exchange.leverage)
    st = State(cfg.runtime.state_db_path)
    chat = ChatClient(openai_key, cfg.chat.model, cfg.chat.temperature, cfg.chat.system_prompt_path)
    return ex, st, chat


def _get_position_for_symbol(positions: List[dict], symbol: str) -> Optional[dict]:
    for p in positions:
        if p.get("symbol") == symbol:
            return p
    return None


PARENT_TF = {"1m": "5m", "5m": "15m", "15m": "1h", "1h": "4h"}


def _build_snapshot(cfg: AppConfig, ex: BybitExchange, extra_data: dict | None) -> dict:
    symbol = cfg.exchange.symbol
    timeframe = cfg.exchange.timeframe
    ohlcv_full = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=200)
    # shrink to reduce tokens while computing features from full
    ohlcv = ohlcv_full[-120:]
    base_features = compute_features(ohlcv_full)

    higher_tf = PARENT_TF.get(timeframe)
    higher_features = None
    if higher_tf:
        try:
            ohlcv_h = ex.fetch_ohlcv(symbol, timeframe=higher_tf, limit=200)
            higher_features = {"timeframe": higher_tf, **compute_features(ohlcv_h)}
        except Exception:
            higher_features = None
    balance = ex.fetch_balance()
    positions = ex.fetch_positions([symbol])
    position = _get_position_for_symbol(positions, symbol) if positions else None
    open_orders = ex.fetch_open_orders(symbol)
    ticker = ex.fetch_ticker(symbol)
    # order book summary
    try:
        ob = ex.fetch_order_book(symbol, limit=5)
        bids = ob.get("bids") or []
        asks = ob.get("asks") or []
        best_bid = bids[0][0] if bids else None
        best_ask = asks[0][0] if asks else None
        spread = (best_ask - best_bid) if (best_bid and best_ask) else None
        sum_bid_vol = sum(b[1] for b in bids[:5]) if bids else None
        sum_ask_vol = sum(a[1] for a in asks[:5]) if asks else None
        ob_summary = {
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread": spread,
            "sum_bid_vol_top5": sum_bid_vol,
            "sum_ask_vol_top5": sum_ask_vol,
        }
    except Exception:
        ob_summary = None
    mi = ex.get_market_info()
    # trades flow (last minute)
    trades = ex.fetch_trades(symbol, limit=200)
    now_ms = int(time.time() * 1000)
    window_ms = 60_000
    buy_vol = 0.0
    sell_vol = 0.0
    tick_count = 0
    for t in trades or []:
        ts = int(t.get("timestamp") or 0)
        if now_ms - ts <= window_ms:
            tick_count += 1
            side = t.get("side")
            amt = float(t.get("amount") or 0)
            if side == "buy":
                buy_vol += amt
            elif side == "sell":
                sell_vol += amt
    cvd_delta = buy_vol - sell_vol

    # funding and open interest (if available)
    fr = ex.fetch_funding_rate(symbol)
    oi = ex.fetch_open_interest(symbol)

    market_snapshot = {
        "ticker": ticker,
        "market_info": {
            "price_step": mi.price_step,
            "amount_step": mi.amount_step,
            "min_price": mi.min_price,
            "max_price": mi.max_price,
            "min_amount": mi.min_amount,
            "max_amount": mi.max_amount,
        },
        "order_book_summary": ob_summary,
        "features": {
            "base": base_features,
            "higher": higher_features,
        },
        "trades_flow_1m": {
            "buy_volume": buy_vol,
            "sell_volume": sell_vol,
            "ticks_per_min": tick_count,
            "cvd_delta": cvd_delta,
        },
        "funding": fr,
        "open_interest": oi,
    }
    account_snapshot = {
        "balance": balance,
        "position": position,
        "open_orders": open_orders,
    }
    return {
        "config": {
            "symbol": symbol,
            "timeframe": timeframe,
            "post_only": cfg.exchange.post_only,
            # risk.defaults (default_tp_pct/default_sl_pct) намеренно не включаем в снапшот,
            # чтобы модель всегда указывала TP/SL явно
        },
        "account_snapshot": account_snapshot,
        "market_snapshot": market_snapshot,
        "recent_ohlcv": ohlcv,
        "extra_data": extra_data or {},
    }


def _execute_action(cfg: AppConfig, ex: BybitExchange, st: State, decision: Decision, snapshot: dict):
    symbol = cfg.exchange.symbol
    dry = cfg.runtime.dry_run
    risk_limits = RiskLimits(
        max_open_orders=cfg.limits.max_open_orders,
        max_position_usdt=cfg.limits.max_position_usdt,
        max_orders_per_hour=cfg.limits.max_orders_per_hour,
        reduce_only_when_closing=cfg.risk.reduce_only_when_closing,
    )

    if st.has_action(decision.idempotency_key):
        console.log(f"Idempotent skip for key={decision.idempotency_key}")
        return

    action = decision.action
    params = decision.params

    if action == "place_order":
        side = params.side  # type: ignore[attr-defined]
        price = float(params.price)  # type: ignore[attr-defined]
        qty = float(params.qty)  # type: ignore[attr-defined]
        post_only = params.post_only if getattr(params, 'post_only', None) is not None else cfg.exchange.post_only  # type: ignore[attr-defined]
        tif = getattr(params, 'time_in_force', None)

        ticker = snapshot["market_snapshot"]["ticker"]
        last_price = float(ticker.get("last") or ticker.get("close") or 0) or price
        additional_usdt = abs(last_price * qty)

        open_orders = snapshot["account_snapshot"]["open_orders"]
        if not check_open_orders_limit(len(open_orders), risk_limits):
            st.record_action(decision.idempotency_key, "rejected", "open_orders_limit")
            console.log("Open orders limit reached; rejecting")
            return

        if not check_orders_per_hour(st.orders_last_hour(), risk_limits):
            st.record_action(decision.idempotency_key, "rejected", "orders_per_hour_limit")
            console.log("Orders/hour limit reached; rejecting")
            return

        position = snapshot["account_snapshot"].get("position") or {}
        current_pos_size = float(position.get("contracts") or position.get("contractsSize") or position.get("size") or 0)
        current_side = position.get("side")  # long/short
        current_avg_price = float(position.get("entryPrice") or position.get("entry_price") or last_price)
        current_usdt_val = abs(current_avg_price * current_pos_size)

        if would_exceed_position_usdt(current_usdt_val, additional_usdt, risk_limits):
            st.record_action(decision.idempotency_key, "rejected", "max_position_usdt")
            console.log("Max position USDT exceeded; rejecting")
            return

        # Check free USDT for estimated required margin
        balance = snapshot["account_snapshot"].get("balance") or {}
        usdt_wallet = balance.get("USDT") or {}
        free_usdt = float(usdt_wallet.get("free") or usdt_wallet.get("available") or 0)
        required_margin = (additional_usdt / max(1, cfg.exchange.leverage)) * 1.02
        if free_usdt < required_margin:
            # Try to auto-reduce qty down to budget if possible
            mi = ex.get_market_info()
            amount_step = mi.amount_step or 0.001
            min_amount = mi.min_amount or amount_step
            max_affordable_qty = (free_usdt * cfg.exchange.leverage) / max(1e-9, last_price)
            # round down to step
            from bot.formatting import round_to_step_down
            adj_qty = round_to_step_down(max_affordable_qty, amount_step)
            # Ensure >= min_amount
            if adj_qty >= (min_amount or 0) and adj_qty > 0:
                console.print(f"[yellow]Reducing qty from {qty} to {adj_qty} to fit margin budget {free_usdt} USDT.")
                qty = adj_qty
                additional_usdt = abs(last_price * qty)
                required_margin = (additional_usdt / max(1, cfg.exchange.leverage)) * 1.02
            else:
                st.record_action(decision.idempotency_key, "rejected", f"insufficient_funds free={free_usdt} required~={required_margin}")
                console.print(f"[yellow]Insufficient free USDT (~{free_usdt}) for margin (~{required_margin}). Skipping order.")
                return

        # TP/SL: требуем явного указания моделью (никаких значений по умолчанию)
        take_profit = float(params.take_profit)  # type: ignore[attr-defined]
        stop_loss = float(params.stop_loss)      # type: ignore[attr-defined]

        # normalize
        nprice, nqty = ex.normalize_price_amount(price, qty)
        # side-aware adjustment to avoid crossing the book; enable post_only if would cross
        ob = snapshot["market_snapshot"]["order_book_summary"] or {}
        best_bid = ob.get("best_bid") if isinstance(ob, dict) else None
        best_ask = ob.get("best_ask") if isinstance(ob, dict) else None
        mi2 = ex.get_market_info()
        step = mi2.price_step or 0.0
        auto_post_only = False
        if side == "buy" and best_ask:
            limit_cross = nprice >= best_ask
            if limit_cross and step:
                nprice = min(nprice, best_ask - step)
                auto_post_only = True
        if side == "sell" and best_bid:
            limit_cross = nprice <= best_bid
            if limit_cross and step:
                nprice = max(nprice, best_bid + step)
                auto_post_only = True
        if auto_post_only:
            post_only = True
        console.log(f"Normalized price={nprice} qty={nqty}")

        client_oid = f"gptbot-{int(time.time())}-{shortuuid.ShortUUID().random(length=5)}"
        if dry:
            console.log(f"[dry-run] Would place LIMIT {side} {nqty} @ {nprice} clientOrderId={client_oid}")
            st.record_order_attempt()
            st.record_action(decision.idempotency_key, "completed", json.dumps({"dry": True}))
            return

        try:
            st.record_order_attempt()
            order = ex.create_limit_order(
                symbol,
                side,
                nqty,
                nprice,
                client_order_id=client_oid,
                time_in_force=tif or "GTC",
                reduce_only=False,
                post_only=post_only,
                take_profit=take_profit,
                stop_loss=stop_loss,
            )
            orders_placed_total.inc()
            st.record_action(decision.idempotency_key, "completed", json.dumps(order))
            console.log(f"Order placed id={order.get('id')}")
        except Exception as e:
            errors_total.inc()
            # Не допускаем выставления ордеров без TP/SL — никаких фолбэков
            st.record_action(decision.idempotency_key, "error", str(e))
            console.print(f"[red]Order placement failed (no fallback without TP/SL): {e}")

    elif action == "cancel_order":
        order_id = getattr(params, 'order_id', None)
        all_for_symbol = getattr(params, 'all_for_symbol', None)
        if dry:
            console.log(f"[dry-run] Would cancel order_id={order_id} all_for_symbol={all_for_symbol}")
            st.record_action(decision.idempotency_key, "completed", json.dumps({"dry": True}))
            return
        try:
            if order_id:
                ex.cancel_order(order_id, symbol)
            elif all_for_symbol:
                ex.cancel_all_orders(symbol)
            st.record_action(decision.idempotency_key, "completed", None)
        except Exception as e:
            errors_total.inc()
            st.record_action(decision.idempotency_key, "error", str(e))
            console.print(f"[red]Cancel failed: {e}")

    elif action == "close_position":
        size_pct = getattr(params, 'size_pct', None) or 100.0
        reduce_only = getattr(params, 'reduce_only', None)
        if reduce_only is None:
            reduce_only = True if cfg.risk.reduce_only_when_closing else True

        # Determine side and size to close
        position = snapshot["account_snapshot"].get("position") or {}
        pos_size = float(position.get("contracts") or position.get("contractsSize") or position.get("size") or 0)
        if pos_size == 0:
            st.record_action(decision.idempotency_key, "completed", json.dumps({"note": "no position"}))
            return
        pos_side = position.get("side", "long").lower()
        close_side = "sell" if pos_side == "long" else "buy"
        amount = abs(pos_size) * (size_pct / 100.0)
        ticker = snapshot["market_snapshot"]["ticker"]
        bid = float(ticker.get("bid") or ticker.get("bidPrice") or 0)
        ask = float(ticker.get("ask") or ticker.get("askPrice") or 0)
        price = bid if close_side == "sell" else ask
        if not price:
            price = float(ticker.get("last") or ticker.get("close") or 0)
        nprice, namount = ex.normalize_price_amount(price, amount)
        client_oid = f"gptbot-close-{int(time.time())}-{shortuuid.ShortUUID().random(length=5)}"

        if dry:
            console.log(f"[dry-run] Would close {size_pct}% via LIMIT {close_side} {namount} @ {nprice} reduceOnly={reduce_only}")
            st.record_action(decision.idempotency_key, "completed", json.dumps({"dry": True}))
            return

        try:
            order = ex.create_limit_order(
                symbol,
                close_side,
                namount,
                nprice,
                client_order_id=client_oid,
                time_in_force="GTC",
                reduce_only=reduce_only,
                post_only=None,
            )
            orders_placed_total.inc()
            st.record_action(decision.idempotency_key, "completed", json.dumps(order))
            console.log(f"Close order placed id={order.get('id')}")
        except Exception as e:
            errors_total.inc()
            st.record_action(decision.idempotency_key, "error", str(e))
            console.print(f"[red]Close failed: {e}")

    elif action == "do_nothing":
        st.record_action(decision.idempotency_key, "completed", json.dumps({"note": "noop"}))
    else:
        st.record_action(decision.idempotency_key, "rejected", json.dumps({"reason": "unsupported_action"}))


def _collect_extra_data(ex: BybitExchange, symbol: str, requests: List[dict], cache: dict | None = None) -> tuple[dict, bool]:
    out: dict = {}
    fetched_any = False
    now_ts = int(time.time())
    for req in requests:
        kind = req.get("kind")
        args = req.get("args", {})
        if kind == "ohlcv":
            tf = args.get("timeframe", "1m")
            limit = int(args.get("limit", 200))
            out["ohlcv"] = ex.fetch_ohlcv(symbol, timeframe=tf, limit=limit)
            fetched_any = True
        elif kind == "ticker":
            if cache and cache.get("ticker") and (now_ts - cache.get("ts", 0) <= 3):
                out["ticker"] = cache["ticker"]
            else:
                out["ticker"] = ex.fetch_ticker(symbol)
                fetched_any = True
        elif kind == "positions":
            if cache and cache.get("positions") and (now_ts - cache.get("ts", 0) <= 3):
                out["positions"] = cache["positions"]
            else:
                out["positions"] = ex.fetch_positions([symbol])
                fetched_any = True
        elif kind == "balance":
            out["balance"] = ex.fetch_balance()
            fetched_any = True
        elif kind == "open_orders":
            if cache and cache.get("open_orders") and (now_ts - cache.get("ts", 0) <= 3):
                out["open_orders"] = cache["open_orders"]
            else:
                out["open_orders"] = ex.fetch_open_orders(symbol)
                fetched_any = True
        # Other kinds can be added similarly using ccxt methods
    return out, fetched_any


def _one_cycle(cfg: AppConfig, ex: BybitExchange, st: State, chat: ChatClient, remaining_limit: int):
    counters = {
        "remaining_info_requests": remaining_limit,
        "limit": cfg.limits.max_info_requests_per_cycle,
    }
    flags = {"terminal_on_last_info_request": True}
    extra_data: dict = {}
    cache: dict = {"ts": 0, "ticker": None, "positions": None, "open_orders": None, "order_book": None}

    def build_payload(remaining: int) -> dict:
        snap = _build_snapshot(cfg, ex, extra_data)
        # update cache freshness
        cache["ts"] = int(time.time())
        cache["ticker"] = snap["market_snapshot"]["ticker"]
        cache["positions"] = snap["account_snapshot"]["position"]
        cache["open_orders"] = snap["account_snapshot"]["open_orders"]
        cache["order_book"] = snap["market_snapshot"].get("order_book_summary")

        # Policy/constraints to guide the model
        open_orders_count = len(snap["account_snapshot"]["open_orders"] or [])
        orders_last_hour = st.orders_last_hour()
        last_price = float((snap["market_snapshot"]["ticker"] or {}).get("last") or 0)
        position = snap["account_snapshot"].get("position") or {}
        pos_size = float(position.get("contracts") or position.get("size") or 0)
        pos_val_usdt = abs(pos_size * (float(position.get("entryPrice") or last_price)))
        max_remaining_usdt = max(cfg.limits.max_position_usdt - pos_val_usdt, 0)
        allowed_place = (open_orders_count < cfg.limits.max_open_orders) and (orders_last_hour < cfg.limits.max_orders_per_hour) and (max_remaining_usdt > 0)

        policy = {
            "allowed_actions": [a for a in ["place_order" if allowed_place else None, "cancel_order", "close_position", "do_nothing"] if a],
            "constraints": {
                "open_orders": open_orders_count,
                "max_open_orders": cfg.limits.max_open_orders,
                "orders_last_hour": orders_last_hour,
                "max_orders_per_hour": cfg.limits.max_orders_per_hour,
                "max_position_usdt": cfg.limits.max_position_usdt,
                "position_usdt": pos_val_usdt,
                "max_position_usdt_remaining": max_remaining_usdt,
            },
            "hints": [
                "Для модификации цены: сначала cancel_order, затем place_order",
                "На последней попытке — только терминальные действия",
            ],
        }

        payload = {
            **snap,
            "counters": counters | {"remaining_info_requests": remaining},
            "flags": flags,
            "policy": policy,
        }
        if remaining == 1:
            payload["_notice"] = "Внимание: осталась последняя попытка. Верни ТЕРМИНАЛЬНОЕ действие, не запрашивай данные."
        return payload

    remaining = remaining_limit
    while True:
        payload = build_payload(remaining)
        console.log("Snapshot built for %s@%s, candles=200" % (cfg.exchange.symbol, cfg.exchange.timeframe))
        decision = chat.decide(payload, remaining)
        console.log(f"Decision: {decision.action} key={decision.idempotency_key}")
        if decision.action == "request_data":
            # should only happen when remaining > 1 due to validation
            requests = decision.params.requests  # type: ignore[attr-defined]
            data, fetched_any = _collect_extra_data(ex, cfg.exchange.symbol, [r.model_dump() for r in requests], cache)
            extra_data.update(data)
            if fetched_any:
                remaining -= 1
            if remaining <= 0:
                # force terminal next
                remaining = 1
            continue
        else:
            _execute_action(cfg, ex, st, decision, _build_snapshot(cfg, ex, extra_data))
            break


@app.command()
def check(
    config: str = typer.Option("config.yaml", help="Путь к YAML-конфигу"),
    env_file: Optional[str] = typer.Option(None, help="Путь к .env с ключами"),
    symbol: Optional[str] = typer.Option(None, help="Переопределить символ"),
    timeframe: Optional[str] = typer.Option(None, help="Переопределить таймфрейм"),
    testnet: Optional[bool] = typer.Option(None, help="Вкл/выкл sandbox"),
    dry_run: Optional[bool] = typer.Option(None, help="Сухой запуск"),
):
    cfg = _load_cfg(config, {"symbol": symbol, "timeframe": timeframe, "testnet": testnet, "dry_run": dry_run})
    ex, st, chat = _init_clients(cfg, env_file)
    mi = ex.get_market_info()
    console.print("[green]Exchange initialized successfully")
    console.print(f"Market steps: price_step={mi.price_step} amount_step={mi.amount_step}")
    try:
        bal = ex.fetch_balance()
        usdt = bal.get("USDT") or {}
        console.print(f"USDT free={usdt.get('free')} total={usdt.get('total')}")
    except Exception as e:
        console.print(f"[yellow]Balance fetch failed: {e}")


@app.command()
def once(
    config: str = typer.Option("config.yaml", help="Путь к YAML-конфигу"),
    env_file: Optional[str] = typer.Option(None, help="Путь к .env с ключами"),
    symbol: Optional[str] = typer.Option(None, help="Переопределить символ"),
    timeframe: Optional[str] = typer.Option(None, help="Переопределить таймфрейм"),
    testnet: Optional[bool] = typer.Option(None, help="Вкл/выкл sandbox"),
    dry_run: Optional[bool] = typer.Option(None, help="Сухой запуск"),
):
    cfg = _load_cfg(config, {"symbol": symbol, "timeframe": timeframe, "testnet": testnet, "dry_run": dry_run})
    start_metrics_server_if_enabled(cfg.metrics.enabled, cfg.metrics.port)
    ex, st, chat = _init_clients(cfg, env_file)
    _one_cycle(cfg, ex, st, chat, cfg.limits.max_info_requests_per_cycle)
    cycles_total.inc()


@app.command()
def run(
    config: str = typer.Option("config.yaml", help="Путь к YAML-конфигу"),
    env_file: Optional[str] = typer.Option(None, help="Путь к .env с ключами"),
    symbol: Optional[str] = typer.Option(None, help="Переопределить символ"),
    timeframe: Optional[str] = typer.Option(None, help="Переопределить таймфрейм"),
    testnet: Optional[bool] = typer.Option(None, help="Вкл/выкл sandbox"),
    dry_run: Optional[bool] = typer.Option(None, help="Сухой запуск"),
):
    cfg = _load_cfg(config, {"symbol": symbol, "timeframe": timeframe, "testnet": testnet, "dry_run": dry_run})
    start_metrics_server_if_enabled(cfg.metrics.enabled, cfg.metrics.port)
    ex, st, chat = _init_clients(cfg, env_file)
    tf = cfg.exchange.timeframe
    console.print(f"[cyan]Starting loop on closed candles: {cfg.exchange.symbol}@{tf}")
    while True:
        wait_for_next_closed_candle(tf)
        try:
            _one_cycle(cfg, ex, st, chat, cfg.limits.max_info_requests_per_cycle)
            cycles_total.inc()
        except Exception as e:
            errors_total.inc()
            console.print(f"[red]Cycle error: {e}")


def main():
    # uvloop optionally
    try:
        import uvloop  # type: ignore
        uvloop.install()
    except Exception:
        pass
    app()


if __name__ == "__main__":
    main()
