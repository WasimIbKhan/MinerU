# Local addition (not upstream): live parse-progress tracking for the FastAPI server.
#
# The pipeline backend reports its work through tqdm bars — most usefully
# "Processing pages" in pipeline_analyze.py, whose total is the document's real
# page count. We patch tqdm's __init__/update to mirror every bar tick into a
# single "current task" entry (task execution is serialized by the request
# semaphore, so one slot is enough), exposed via GET /progress/current.
#
# Percent mapping: each recognized bar category owns a [start, end] band of the
# overall 0-100 range and the reported percent is monotonically non-decreasing.
# The per-window model bars (Layout/MFD/MFR/OCR/Table Predict) animate a small
# 3-16 "warm-up" band — they restart every 64-page processing window, and the
# monotonic clamp silences the repeats — after which the page-accurate
# "Processing pages" bar owns 16-95. Unknown bars never move the percent; the
# genuine 100 comes from the task completing. If upstream renames its bars this
# degrades to a quiet percent, never a wrong parse.

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from loguru import logger

_CURRENT: Optional[Dict[str, Any]] = None

# The API semaphore may allow >1 concurrent task; tqdm bars are process-global
# and cannot be attributed to a task. While more than one task is executing we
# stop moving the percent entirely — quiet-but-honest beats interleaved-wrong.
_ACTIVE_TASKS = 0

# (substring-of-desc, friendly stage label, band start %, band end %).
# Case-insensitive, first match wins — specific needles before generic ones
# ("Table-ocr det" must hit "table", not "ocr-det").
_STAGE_BANDS = [
    ("processing pages", "Processing pages", 16, 95),
    ("table", "Recognizing tables", 15, 16),
    ("layout", "Analyzing layout", 3, 6),
    ("mfd", "Detecting formulas", 6, 8),
    ("mfr", "Recognizing formulas", 8, 10),
    ("ocr-det", "Detecting text", 10, 12),
    ("ocr-rec", "Recognizing text", 12, 15),
    ("seal", "Recognizing text", 12, 15),
]


def progress_task_started(task_id: str, file_names: List[str]) -> None:
    global _CURRENT, _ACTIVE_TASKS
    _ACTIVE_TASKS += 1
    _CURRENT = {
        "task_id": task_id,
        "file_names": list(file_names or []),
        "percent": 0,
        "stage": "Starting",
        "done": False,
        "updated_at": time.time(),
    }


def progress_task_finished(task_id: str) -> None:
    global _ACTIVE_TASKS
    _ACTIVE_TASKS = max(0, _ACTIVE_TASKS - 1)
    entry = _CURRENT
    if entry is not None and entry.get("task_id") == task_id:
        entry.update(percent=100, stage="Complete", done=True, updated_at=time.time())


def get_current_progress() -> Optional[Dict[str, Any]]:
    return dict(_CURRENT) if _CURRENT is not None else None


def _progress_on_bar(bar) -> None:
    """Mirror a tqdm bar's state into the current task's progress entry."""
    entry = _CURRENT
    if entry is None or entry["done"]:
        return  # model loading / unrelated tqdm usage
    if _ACTIVE_TASKS > 1:
        return  # concurrent tasks: bars are unattributable, stay quiet

    desc = (getattr(bar, "desc", "") or "").lower()
    total = getattr(bar, "total", None)
    n = getattr(bar, "n", 0) or 0

    for needle, label, band_start, band_end in _STAGE_BANDS:
        if needle in desc:
            if total:
                fraction = max(0.0, min(1.0, n / total))
                percent = int(band_start + fraction * (band_end - band_start))
            else:
                percent = band_start
            # Monotonic: a repeated per-window bar never rolls us back.
            if percent > entry["percent"]:
                entry["percent"] = percent
                entry["stage"] = label
            elif entry["stage"] != label and percent == entry["percent"]:
                entry["stage"] = label
            entry["updated_at"] = time.time()
            return
    # Unknown bar: leave percent/stage alone.


def install_tqdm_progress_hook() -> None:
    """Patch tqdm class methods so every bar tick feeds _progress_on_bar.

    Patching the class (not replacing it) covers modules that already did
    `from tqdm import tqdm`. Failures here must never break parsing — worst
    case the progress endpoint just stays quiet.
    """
    try:
        from tqdm import tqdm as tqdm_cls
    except ImportError:
        logger.warning("tqdm not importable; parse progress reporting disabled")
        return
    if getattr(tqdm_cls, "_mineru_progress_hooked", False):
        return

    orig_init = tqdm_cls.__init__
    orig_update = tqdm_cls.update

    def patched_init(self, *args, **kwargs):
        orig_init(self, *args, **kwargs)
        try:
            _progress_on_bar(self)
        except Exception:  # noqa: BLE001
            pass

    def patched_update(self, n=1):
        result = orig_update(self, n)
        try:
            _progress_on_bar(self)
        except Exception:  # noqa: BLE001
            pass
        return result

    tqdm_cls.__init__ = patched_init
    tqdm_cls.update = patched_update
    tqdm_cls._mineru_progress_hooked = True
    logger.info("tqdm parse-progress hook installed")
