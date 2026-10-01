"""A small, dependency-free metrics registry rendered in the Prometheus text
format at GET /metrics. Counters and histograms are updated in-process;
gauges that reflect stored data (active calls, open escalations, ...) are
read when the endpoint is scraped."""

import math
import threading
from collections.abc import Callable, Iterable, Sequence

_DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)


def _labels(names: Sequence[str], values: Sequence[str]) -> str:
    if not names:
        return ""
    pairs = ",".join(f'{n}="{_escape(v)}"' for n, v in zip(names, values))
    return "{" + pairs + "}"


def _escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _number(value: float) -> str:
    if math.isinf(value):
        return "+Inf" if value > 0 else "-Inf"
    return repr(float(value)) if not float(value).is_integer() else str(int(value))


class _Metric:
    kind = ""

    def __init__(self, name: str, help_text: str, label_names: Sequence[str] = ()) -> None:
        self.name = name
        self.help = help_text
        self.label_names = tuple(label_names)
        self._lock = threading.Lock()

    def header(self) -> list[str]:
        return [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} {self.kind}"]


class Counter(_Metric):
    kind = "counter"

    def __init__(self, name: str, help_text: str, label_names: Sequence[str] = ()) -> None:
        super().__init__(name, help_text, label_names)
        self._values: dict[tuple[str, ...], float] = {}

    def inc(self, *label_values: str, amount: float = 1.0) -> None:
        with self._lock:
            self._values[label_values] = self._values.get(label_values, 0.0) + amount

    def value(self, *label_values: str) -> float:
        return self._values.get(label_values, 0.0)

    def render(self) -> list[str]:
        with self._lock:
            items = sorted(self._values.items())
        return self.header() + [
            f"{self.name}{_labels(self.label_names, k)} {_number(v)}" for k, v in items
        ]


class Gauge(_Metric):
    """Set directly (inc/dec) or computed at scrape time by a callback that
    returns {label values: value}."""

    kind = "gauge"

    def __init__(
        self,
        name: str,
        help_text: str,
        label_names: Sequence[str] = (),
        callback: Callable[[], dict[tuple[str, ...], float]] | None = None,
    ) -> None:
        super().__init__(name, help_text, label_names)
        self._value = 0.0
        self.callback = callback

    def inc(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value += amount

    def dec(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value -= amount

    def value(self) -> float:
        return self._value

    def render(self) -> list[str]:
        if self.callback is None:
            return self.header() + [f"{self.name} {_number(self._value)}"]
        values = self.callback()
        return self.header() + [
            f"{self.name}{_labels(self.label_names, k)} {_number(v)}"
            for k, v in sorted(values.items())
        ]


class Histogram(_Metric):
    kind = "histogram"

    def __init__(
        self,
        name: str,
        help_text: str,
        label_names: Sequence[str] = (),
        buckets: Iterable[float] = _DEFAULT_BUCKETS,
    ) -> None:
        super().__init__(name, help_text, label_names)
        self.buckets = tuple(sorted(buckets)) + (math.inf,)
        self._series: dict[tuple[str, ...], list[float]] = {}

    def observe(self, value: float, *label_values: str) -> None:
        with self._lock:
            # [bucket counts..., sum, count]
            series = self._series.setdefault(label_values, [0.0] * (len(self.buckets) + 2))
            for index, bound in enumerate(self.buckets):
                if value <= bound:
                    series[index] += 1
            series[-2] += value
            series[-1] += 1

    def render(self) -> list[str]:
        with self._lock:
            items = sorted((k, list(v)) for k, v in self._series.items())
        lines = self.header()
        for key, series in items:
            for bound, count in zip(self.buckets, series):
                labels = _labels(self.label_names + ("le",), key + (_number(bound),))
                lines.append(f"{self.name}_bucket{labels} {_number(count)}")
            base = _labels(self.label_names, key)
            lines.append(f"{self.name}_sum{base} {_number(series[-2])}")
            lines.append(f"{self.name}_count{base} {_number(series[-1])}")
        return lines


class MetricsRegistry:
    def __init__(self) -> None:
        self._metrics: dict[str, _Metric] = {}
        self._lock = threading.Lock()

    def register(self, metric: _Metric) -> _Metric:
        with self._lock:
            self._metrics[metric.name] = metric
        return metric

    def unregister(self, name: str) -> None:
        with self._lock:
            self._metrics.pop(name, None)

    def render(self) -> str:
        with self._lock:
            metrics = list(self._metrics.values())
        lines: list[str] = []
        for metric in metrics:
            try:
                lines.extend(metric.render())
            except Exception:
                # One failing data source must not hide the other metrics.
                lines.append(f"# {metric.name} unavailable")
        return "\n".join(lines) + "\n"


REGISTRY = MetricsRegistry()

HTTP_REQUESTS = REGISTRY.register(
    Counter(
        "http_requests_total",
        "HTTP requests handled, by method, route template and status code.",
        ("method", "route", "status"),
    )
)
HTTP_REQUEST_DURATION = REGISTRY.register(
    Histogram(
        "http_request_duration_seconds",
        "Time taken to handle HTTP requests.",
        ("method", "route"),
    )
)
TELEPHONY_STREAMS_OPEN = REGISTRY.register(
    Gauge("telephony_streams_open", "Telephony media streams open on this instance.")
)
POST_CALL_REPAIRS = REGISTRY.register(
    Counter(
        "post_call_repairs_total",
        "Post-call processing retries, by outcome (repaired, failed, gave_up).",
        ("outcome",),
    )
)
