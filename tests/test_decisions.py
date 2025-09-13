import pytest
from pydantic import ValidationError

from bot.decisions import validate_decision


def test_place_order_valid():
    decision = {
        "action": "place_order",
        "idempotency_key": "abc",
        "params": {
            "side": "buy",
            "price": 100.0,
            "qty": 0.1,
            "take_profit": None,
            "stop_loss": None,
            "post_only": None,
            "time_in_force": None,
        },
    }
    d = validate_decision(decision, remaining_info_requests=5)
    assert d.action == "place_order"


def test_request_data_forbidden_on_last_attempt():
    decision = {
        "action": "request_data",
        "idempotency_key": "abc",
        "params": {
            "requests": [
                {"kind": "ticker", "args": {}},
            ]
        },
    }
    with pytest.raises(ValidationError):
        validate_decision(decision, remaining_info_requests=1)


def test_idempotency_in_state(tmp_path):
    from bot.state import State
    st = State(tmp_path / "state.db")
    key = "unique-1"
    assert not st.has_action(key)
    st.record_action(key, "completed", None)
    assert st.has_action(key)

