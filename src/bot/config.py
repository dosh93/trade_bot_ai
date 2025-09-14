from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError


class ExchangeConfig(BaseModel):
    symbol: str = Field("ETH/USDT:USDT")
    timeframe: str = Field("5m")
    leverage: int = Field(5, ge=1)
    margin_mode: str = Field("cross")
    post_only: bool = Field(False)
    testnet: bool = Field(False)


class LimitsConfig(BaseModel):
    max_info_requests_per_cycle: int = Field(5, ge=1)
    max_open_orders: int = Field(5, ge=0)
    max_position_usdt: float = Field(1000.0, ge=0.0)
    max_orders_per_hour: int = Field(10, ge=0)


class RiskConfig(BaseModel):
    allow_pyramiding: bool = Field(False)
    max_additions: int = Field(0, ge=0)
    reduce_only_when_closing: bool = Field(True)


class ChatConfig(BaseModel):
    model: str = Field("gpt-4o-mini")
    temperature: float = Field(0)
    system_prompt_path: str = Field("prompts/system.md")


class LogsConfig(BaseModel):
    level: str = Field("INFO")


class MetricsConfig(BaseModel):
    enabled: bool = Field(False)
    port: int = Field(9308)


class RuntimeConfig(BaseModel):
    dry_run: bool = Field(False)
    state_db_path: str = Field("state.db")


class AppConfig(BaseModel):
    exchange: ExchangeConfig = Field(default_factory=ExchangeConfig)
    limits: LimitsConfig = Field(default_factory=LimitsConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    chat: ChatConfig = Field(default_factory=ChatConfig)
    logs: LogsConfig = Field(default_factory=LogsConfig)
    metrics: MetricsConfig = Field(default_factory=MetricsConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)


def deep_update(d: dict, u: dict) -> dict:
    for k, v in u.items():
        if isinstance(v, dict) and isinstance(d.get(k), dict):
            d[k] = deep_update(d.get(k, {}), v)
        else:
            d[k] = v
    return d


def env_overlay(prefix: str = "BGB__") -> dict:
    """Overlay settings from environment variables with a prefix.
    Example: BGB__EXCHANGE__SYMBOL=BTC/USDT:USDT -> {"exchange": {"symbol": "BTC/USDT:USDT"}}
    Booleans: true/false/1/0; integers and floats auto-cast when possible.
    """
    out: dict = {}
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        path = key[len(prefix):].lower().split("__")
        ref = out
        for p in path[:-1]:
            ref = ref.setdefault(p, {})
        # cast
        v: object = value
        if value.lower() in {"true", "false"}:
            v = value.lower() == "true"
        else:
            try:
                if "." in value:
                    v = float(value)
                else:
                    v = int(value)
            except ValueError:
                v = value
        ref[path[-1]] = v
    return out


def load_config(path: str | Path | None) -> AppConfig:
    load_dotenv(override=False)
    base: dict = {}
    if path:
        with open(path, "r", encoding="utf-8") as f:
            base = yaml.safe_load(f) or {}

    # overlay from env prefix
    overlay = env_overlay()
    merged = deep_update(base, overlay)

    try:
        cfg = AppConfig.model_validate(merged)
    except ValidationError as e:
        raise RuntimeError(f"Invalid config: {e}")

    return cfg

