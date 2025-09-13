from __future__ import annotations

import threading
from typing import Optional

from prometheus_client import Counter, start_http_server


cycles_total = Counter("bot_cycles_total", "Total trading cycles executed")
orders_placed_total = Counter("bot_orders_placed_total", "Total orders placed")
errors_total = Counter("bot_errors_total", "Total errors")


def start_metrics_server_if_enabled(enabled: bool, port: int):
    if not enabled:
        return

    def _run():
        start_http_server(port)

    t = threading.Thread(target=_run, daemon=True)
    t.start()


