# Local addition (WasimIbKhan/MinerU local-patches-v4, not upstream): live
# per-page progress for API parse jobs.
#
# PDF analysis runs in processing windows (64 pages by default). Each window
# logs its page range and then drives tqdm bars: "Layout Predict" ticks once per
# page of the window, "OCR-det"/"OCR-rec" per text crop. Wrapping that window
# log and tqdm lets the running job's JobProgress carry percent, stage,
# pages_done and pages_total, read through the normal task status endpoints.
#
# Percent: model loading fills 0-5, pages fill 5-95 (interpolated inside the
# current window from its bars), and the job finishing supplies 100. It never
# moves backwards. With more than one job running the bars cannot be
# attributed, so progress holds still. If upstream renames these hooks the
# result is stage-only progress, never a failed parse.

from __future__ import annotations

import functools
import threading
from typing import Any

from loguru import logger

_lock = threading.Lock()
_running: list[Any] = []
_window = {"start": 0, "size": 0}

# (tqdm desc substring, stage, window fraction start, end), in the order a window
# runs them (pdf/window.py); first match wins.
_BANDS = (
    ("layout", "Analyzing layout", 0.05, 0.25),
    ("table orientation", "Analyzing tables", 0.25, 0.28),
    ("mfr", "Recognizing formulas", 0.28, 0.55),
    ("table", "Recognizing tables", 0.55, 0.6),
    ("ocr-det", "Detecting text", 0.6, 0.8),
    ("ocr-rec", "Recognizing text", 0.8, 0.95),
)


def track(run_job):
    """Wrap the API server's job runner so its JobProgress is live while it runs."""
    @functools.wraps(run_job)
    async def tracked(rec: Any, *args: Any, **kwargs: Any) -> None:
        begin(rec.progress)
        try:
            await run_job(rec, *args, **kwargs)
        finally:
            end(rec.progress, completed=rec.status in {"completed", "partial"})
    return tracked


def begin(progress: Any) -> None:
    install()
    with _lock:
        _running.append(progress)
        progress.percent, progress.stage = 0, "Starting"


def end(progress: Any, completed: bool) -> None:
    with _lock:
        if progress in _running:
            _running.remove(progress)
        if completed:
            progress.percent, progress.stage = 100, "Complete"
            if progress.pages_total:
                progress.pages_done = progress.pages_total


def _advance(stage: str, percent: int, **pages: int) -> None:
    with _lock:
        if len(_running) != 1:
            return
        progress = _running[0]
        for key, value in pages.items():
            setattr(progress, key, value)
        if percent >= (progress.percent or 0):
            progress.percent, progress.stage = min(percent, 95), stage


def _page_percent(progress: Any, window_fraction: float) -> int:
    total = progress.pages_total or 0
    pages = _window["start"] + _window["size"] * max(0.0, min(1.0, window_fraction))
    return 5 + int(90 * pages / total) if total else 5


def _on_plan(page_count: int, *_args: Any) -> None:
    _window.update(start=0, size=0)
    _advance("Analyzing pages", 5, pages_total=page_count, pages_done=0)


def _on_window(window: Any, page_count: int, image_count: int) -> None:
    _window.update(start=window.start, size=image_count)
    with _lock:
        progress = _running[0] if len(_running) == 1 else None
    if progress is not None:
        _advance("Analyzing layout", _page_percent(progress, 0.0), pages_done=window.start, pages_total=page_count)


def _on_bar(bar: Any) -> None:
    with _lock:
        progress = _running[0] if len(_running) == 1 else None
    if progress is None:
        return
    desc = (getattr(bar, "desc", "") or "").lower()
    total, n = getattr(bar, "total", None), getattr(bar, "n", 0) or 0
    fraction = n / total if total else 0.0
    if "loading weights" in desc and not progress.pages_total:
        _advance("Loading models", 1 + int(4 * fraction))
        return
    for needle, stage, start, stop in _BANDS:
        if needle in desc:
            _advance(stage, _page_percent(progress, start + fraction * (stop - start)))
            return


def install() -> None:
    """Idempotently wrap tqdm and the PDF window logs. Never raises."""
    try:
        from tqdm import tqdm as bar_cls

        from ..backend.analysis.pdf import window as pdf_window
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"parse progress disabled: {exc}")
        return
    if getattr(bar_cls, "_mineru_progress_hooked", False):
        return

    def observe(fn, hook):
        def wrapped(*args, **kwargs):
            result = fn(*args, **kwargs)
            try:
                hook(*args)
            except Exception:  # noqa: BLE001
                pass
            return result
        return wrapped

    bar_cls.__init__ = observe(bar_cls.__init__, lambda bar, *_: _on_bar(bar))
    bar_cls.update = observe(bar_cls.update, lambda bar, *_: _on_bar(bar))
    for name, hook in (("_log_processing_window_plan", _on_plan), ("_log_processing_window", _on_window)):
        if hasattr(pdf_window, name):
            setattr(pdf_window, name, observe(getattr(pdf_window, name), hook))
    bar_cls._mineru_progress_hooked = True
    logger.info("parse progress hooks installed")
