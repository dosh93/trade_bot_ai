from bot.formatting import MarketInfo, normalize_price, normalize_amount


def test_normalize_rounding_price_amount():
    mi = MarketInfo(price_step=0.01, amount_step=0.001, min_price=None, max_price=None, min_amount=None, max_amount=None)
    assert normalize_price(123.4567, mi) == 123.45
    assert normalize_amount(0.123456, mi) == 0.123


def test_clamp_min_max():
    mi = MarketInfo(price_step=0.01, amount_step=0.01, min_price=10.0, max_price=20.0, min_amount=0.1, max_amount=5.0)
    assert normalize_price(9.99, mi) == 10.0
    assert normalize_price(21.23, mi) == 20.0
    assert normalize_amount(0.05, mi) == 0.1
    assert normalize_amount(10.0, mi) == 5.0
