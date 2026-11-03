"""Optional per-request observer; observability never changes enforcement."""
from contextlib import contextmanager
from contextvars import ContextVar

_observer = ContextVar("firewall_progress_observer", default=None)
_phase = ContextVar("firewall_progress_phase", default={"phase": "input"})


def emit_progress(**event):
    callback = _observer.get()
    if callback is not None:
        try:
            callback({**_phase.get(), **event})
        except Exception:
            pass  # a display/observer failure cannot authorize or stop a tool


@contextmanager
def observe_progress(callback):
    token = _observer.set(callback)
    try:
        yield
    finally:
        _observer.reset(token)


@contextmanager
def progress_phase(phase, **metadata):
    token = _phase.set({"phase": phase, **metadata})
    try:
        yield
    finally:
        _phase.reset(token)


def layer_summary(result):
    keys = ("decision", "confidence", "reason", "latency_ms", "degraded", "top_attack_similarity",
            "top_benign_similarity", "margin", "matched_view", "units_scored")
    summary = {key: result[key] for key in keys if key in result}
    detail_keys = ("max_window_score", "threshold", "windows", "side", "verdict", "category", "reason",
                   "provider", "model", "cached", "full_text_reviewed", "error")
    details = result.get("details") or {}
    summary.update({key: details[key] for key in detail_keys if key in details})
    return summary
