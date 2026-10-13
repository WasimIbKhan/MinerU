# Local addition (WasimIbKhan/MinerU local-patches-v4, not upstream).
# docvortex's resize_image is single-threaded pure code, about 50x slower than
# cv2.resize (9 ms vs 0.18 ms per crop, max pixel difference 1), and OCR
# detection resizes every text crop, so that stage ends up CPU-bound. MinerU's
# model preprocessing imports resize_image from here: OpenCV when it is
# installed (the "opencv" extra), docvortex otherwise.

from __future__ import annotations

import math

import numpy as np
from docvortex.image import resize_image as _docvortex_resize_image

try:
    import cv2
except ImportError:
    cv2 = None

_INTERPOLATIONS = {} if cv2 is None else {
    "nearest": cv2.INTER_NEAREST, "linear": cv2.INTER_LINEAR, "cubic": cv2.INTER_CUBIC,
    "area": cv2.INTER_AREA, "lanczos4": cv2.INTER_LANCZOS4,
}


def resize_image(image, size, *, interpolation: str = "linear", scale=None) -> np.ndarray:
    """docvortex.image.resize_image semantics, computed by cv2.resize when possible."""
    if (interpolation not in _INTERPOLATIONS or not isinstance(image, np.ndarray) or image.size == 0
            or image.ndim not in (2, 3) or image.dtype.type not in (np.uint8, np.uint16, np.float32)
            or (image.ndim == 3 and not 1 <= image.shape[2] <= 4)):
        return _docvortex_resize_image(image, size, interpolation=interpolation, scale=scale)
    if size is None:
        if scale is None or len(scale) != 2 or not all(math.isfinite(v) and v > 0 for v in scale):
            raise ValueError("Positive scale is required when size is omitted")
        size = round(image.shape[1] * scale[0]), round(image.shape[0] * scale[1])
    elif scale is not None:
        raise ValueError("Provide size or scale, not both")
    if len(size) != 2 or min(size) <= 0:
        raise ValueError("Invalid image size or interpolation")
    gray = image.ndim == 2 or image.shape[2] == 1
    source = np.ascontiguousarray(image[:, :, 0] if image.ndim == 3 and gray else image)
    size = (int(size[0]), int(size[1]))
    if size == (source.shape[1], source.shape[0]):
        return source.copy()
    return np.ascontiguousarray(cv2.resize(source, size, interpolation=_INTERPOLATIONS[interpolation]))
