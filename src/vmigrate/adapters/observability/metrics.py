from __future__ import annotations

import threading


class NoopMetrics:
    def inc(self, name: str, value: float = 1, **labels: str) -> None:
        pass


class PrometheusMetrics:
    """Exposes counters as vmigrate_<name>_total on an HTTP /metrics endpoint."""

    def __init__(self, port: int | None = None):
        from prometheus_client import Counter, start_http_server  # optional dependency

        self._counter_cls = Counter
        self._counters: dict[str, Counter] = {}
        self._lock = threading.Lock()
        if port:
            start_http_server(port)

    def inc(self, name: str, value: float = 1, **labels: str) -> None:
        with self._lock:
            counter = self._counters.get(name)
            if counter is None:
                counter = self._counter_cls(f"vmigrate_{name}", name, sorted(labels))
                self._counters[name] = counter
        counter.labels(**labels).inc(value)
