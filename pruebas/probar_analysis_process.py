"""Integration smoke test for the real process worker and cached endpoint."""
from __future__ import annotations

import atexit
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app
from alpaca_live import _feed

# This smoke test is read-only: prevent the legacy feed's import-time atexit
# callback from rewriting an otherwise unchanged cache in parent or worker.
atexit.unregister(_feed._save_cache)


if __name__ == "__main__":
    service = app.extensions["live_analysis"]
    deadline = time.time() + 12
    while time.time() < deadline and service.snapshot()["status"] in ("waiting", "calculating"):
        time.sleep(0.05)
    snapshot = service.snapshot()
    if snapshot["status"] not in ("ready", "insufficient"):
        raise AssertionError(snapshot)
    client = app.test_client()
    live_page = client.get("/live")
    if live_page.status_code != 200:
        raise AssertionError(f"/live returned {live_page.status_code}")
    timings = []
    for _ in range(100):
        started = time.perf_counter()
        response = client.get("/api/analysis/live")
        timings.append((time.perf_counter() - started) * 1000)
        if response.status_code != 200 or response.get_json()["decision"] != "ESPERAR":
            raise AssertionError(response.get_data(as_text=True))
    count = service.snapshot()["service"]["calculation_count"]
    time.sleep(0.4)
    if service.snapshot()["service"]["calculation_count"] != count:
        raise AssertionError("unchanged candles were recalculated")
    feed_timings = []
    for _ in range(1000):
        started = time.perf_counter()
        _feed.snapshot()
        feed_timings.append((time.perf_counter() - started) * 1000)
    feed_timings.sort()
    # Baseline measured immediately before integration: p95 = 1.1867 ms.
    # The requested maximum regression is 20 percent.
    if feed_timings[949] > 1.1867 * 1.20:
        raise AssertionError(f"feed snapshot p95 regression: {feed_timings[949]:.4f} ms")
    service.stop()
    timings.sort()
    print({"process_worker": "OK", "live_page": "OK", "status": snapshot["status"],
           "symbol": snapshot.get("symbol"), "last_candle": snapshot.get("last_candle_time"),
           "bias": snapshot.get("bias"), "stale": snapshot.get("stale"),
           "rsi": snapshot.get("values", {}).get("rsi"),
           "macd_histogram": snapshot.get("values", {}).get("macd_histogram"),
           "rows": snapshot.get("row_count"), "calculation_ms": snapshot.get("calculation_ms"),
           "endpoint_median_ms": round(statistics.median(timings), 4),
           "endpoint_p95_ms": round(timings[94], 4),
           "feed_snapshot_median_ms": round(statistics.median(feed_timings), 4),
           "feed_snapshot_p95_ms": round(feed_timings[949], 4),
           "calculation_count": count})
