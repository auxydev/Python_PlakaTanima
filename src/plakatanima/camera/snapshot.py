"""Onaylanan geçişlerin anlık görüntülerini kaydeder."""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np

from plakatanima.recognition.offline import write_image
from plakatanima.recognition.types import BBox

log = logging.getLogger(__name__)

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]+")
_ASCII = str.maketrans("ÇĞİÖŞÜçğıöşü", "CGIOSUcgiosu")


def _slug(text: str) -> str:
    return _UNSAFE.sub("-", text.translate(_ASCII)).strip("-").lower() or "kamera"


def save_snapshot(
    captures_dir: Path,
    image: np.ndarray,
    *,
    camera_name: str,
    plate: str,
    plate_bbox: BBox | None = None,
    when: datetime | None = None,
) -> str:
    """Kareyi (plaka kutusu çizilmiş olarak) kaydeder; ``captures_dir``'e göre yol döndürür."""
    when = when or datetime.now()
    marked = image.copy()
    if plate_bbox is not None:
        b = plate_bbox
        cv2.rectangle(marked, (b.x1 - 3, b.y1 - 3), (b.x2 + 3, b.y2 + 3), (0, 200, 80), 3)
    relative = Path(when.strftime("%Y-%m-%d")) / (
        f"{when.strftime('%H%M%S')}_{_slug(camera_name)}_{_slug(plate)}.jpg"
    )
    write_image(captures_dir / relative, marked, quality=85)
    return relative.as_posix()


def cleanup_snapshots(captures_dir: Path, retention_days: int, now: float | None = None) -> int:
    """Saklama süresi dolan görüntüleri ve boş gün klasörlerini siler."""
    if not captures_dir.is_dir():
        return 0
    cutoff = (now or time.time()) - timedelta(days=retention_days).total_seconds()
    removed = 0
    for path in captures_dir.rglob("*.jpg"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            log.warning("Silinemedi: %s", path)
    for folder in sorted(captures_dir.iterdir(), reverse=True):
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    if removed:
        log.info("%d eski görüntü silindi", removed)
    return removed
