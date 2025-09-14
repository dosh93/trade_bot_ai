from __future__ import annotations

from typing import Literal, Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator, ValidationError


ActionLiteral = Literal[
    "place_order",
    "cancel_order",
    "close_position",
    "do_nothing",
    "request_data",
]


class PlaceOrderParams(BaseModel):
    side: Literal["buy", "sell"]
    price: float
    qty: float
    # TP/SL обязательны: запретить null и отсутствие
    take_profit: float
    stop_loss: float
    post_only: Optional[bool] = None
    time_in_force: Optional[Literal["GTC", "IOC", "FOK"]] = None

    @field_validator("price")
    @classmethod
    def price_positive(cls, v):
        if v <= 0:
            raise ValueError("price must be > 0")
        return float(v)

    @field_validator("qty")
    @classmethod
    def qty_positive(cls, v):
        if v <= 0:
            raise ValueError("qty must be > 0")
        return float(v)

    @field_validator("take_profit", "stop_loss")
    @classmethod
    def tp_sl_positive(cls, v):
        if v is None:
            # избыточная защита: по типу None не пройдёт, но оставим явное сообщение
            raise ValueError("take_profit/stop_loss must be provided")
        if v <= 0:
            raise ValueError("take_profit/stop_loss must be > 0")
        return float(v)


class CancelOrderParams(BaseModel):
    order_id: Optional[str] = None
    all_for_symbol: Optional[bool] = None

    @field_validator("all_for_symbol")
    @classmethod
    def validate_any(cls, v, info):
        values = info.data
        if (values.get("order_id") is None) and (not v):
            # both missing/false -> invalid
            raise ValueError("either order_id or all_for_symbol=true required")
        return v


class ClosePositionParams(BaseModel):
    size_pct: Optional[float] = None  # default 100
    reduce_only: Optional[bool] = None  # default true

    @field_validator("size_pct")
    @classmethod
    def check_range(cls, v):
        if v is None:
            return v
        if v <= 0 or v > 100:
            raise ValueError("size_pct must be in (0, 100]")
        return float(v)


class RequestItem(BaseModel):
    kind: Literal[
        "ohlcv",
        "orderbook",
        "trades",
        "ticker",
        "funding_rate",
        "mark_price",
        "index_price",
        "positions",
        "balance",
        "open_orders",
        "open_interest",
    ]
    args: Dict[str, Any] = Field(default_factory=dict)


class RequestDataParams(BaseModel):
    requests: List[RequestItem]


class DecisionBase(BaseModel):
    action: ActionLiteral
    idempotency_key: str
    params: dict


class Decision(BaseModel):
    action: ActionLiteral
    idempotency_key: str
    params: PlaceOrderParams | CancelOrderParams | ClosePositionParams | RequestDataParams | dict


def validate_decision(decision_dict: dict, remaining_info_requests: int) -> Decision:
    try:
        base = DecisionBase.model_validate(decision_dict)
    except ValidationError as e:
        raise

    action = base.action
    parsed: Decision
    if action == "place_order":
        parsed = Decision(action=action, idempotency_key=base.idempotency_key, params=PlaceOrderParams.model_validate(base.params))
    elif action == "cancel_order":
        parsed = Decision(action=action, idempotency_key=base.idempotency_key, params=CancelOrderParams.model_validate(base.params))
    elif action == "close_position":
        parsed = Decision(action=action, idempotency_key=base.idempotency_key, params=ClosePositionParams.model_validate(base.params))
    elif action == "request_data":
        if remaining_info_requests <= 1:
            # Force a pydantic ValidationError by validating an invalid action
            Decision.model_validate({
                "action": "request_data_forbidden",
                "idempotency_key": base.idempotency_key,
                "params": base.params,
            })
        parsed = Decision(action=action, idempotency_key=base.idempotency_key, params=RequestDataParams.model_validate(base.params))
    elif action == "do_nothing":
        parsed = Decision(action=action, idempotency_key=base.idempotency_key, params={})
    else:
        raise ValidationError.from_exception_data(
            Decision.__name__,
            [
                {
                    "type": "value_error",
                    "loc": ("action",),
                    "msg": f"Unsupported action {action}",
                    "input": decision_dict,
                }
            ],
        )
    return parsed
