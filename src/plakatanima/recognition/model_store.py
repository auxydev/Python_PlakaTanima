"""Araç tespit modellerinin indirilmesi ve önbelleğe alınması.

Varsayılan araç modeli YOLOX'tur (Apache-2.0, Megvii). ONNX dosyaları ilk
kullanımda GitHub sürüm sayfasından indirilir ve SHA-256 ile doğrulanır.
Plaka tespit/OCR modellerini ``fast-alpr`` kendi önbelleğine indirir.
"""

from __future__ import annotations

import hashlib
import logging
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int], None]

_YOLOX_RELEASE = "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0"


class ModelError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ModelSpec:
    name: str
    url: str
    sha256: str
    description: str


YOLOX_MODELS: dict[str, ModelSpec] = {
    spec.name: spec
    for spec in (
        ModelSpec(
            "yolox_nano",
            f"{_YOLOX_RELEASE}/yolox_nano.onnx",
            "c789161ed43c8269fcd4e67c67eeeb4e80c622da2eb296a20bc6007bd18a0b7d",
            "En hafif (3.5 MB) — zayıf donanım",
        ),
        ModelSpec(
            "yolox_tiny",
            f"{_YOLOX_RELEASE}/yolox_tiny.onnx",
            "427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb942bc1cc70b0f7",
            "Hafif (20 MB) — hızlı",
        ),
        ModelSpec(
            "yolox_s",
            f"{_YOLOX_RELEASE}/yolox_s.onnx",
            "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063",
            "Dengeli (35 MB) — önerilen",
        ),
        ModelSpec(
            "yolox_m",
            f"{_YOLOX_RELEASE}/yolox_m.onnx",
            "21ff6cfdeb53b013bac2249599e55f00bff3cfdfdab37ed7a4620818c1d15b3f",
            "Doğru ama yavaş (100 MB) — güçlü işlemci/GPU",
        ),
    )
}


def resolve_yolox_model(
    name_or_path: str,
    models_dir: Path,
    progress: ProgressCallback | None = None,
) -> Path:
    """Model adını (``yolox_s``) veya ``.onnx`` yolunu yerel dosya yoluna çevirir."""
    candidate = Path(name_or_path).expanduser()
    if candidate.suffix.lower() == ".onnx":
        if not candidate.is_file():
            raise ModelError(f"Model dosyası bulunamadı: {candidate}")
        return candidate

    spec = YOLOX_MODELS.get(name_or_path)
    if spec is None:
        known = ", ".join(YOLOX_MODELS)
        raise ModelError(f"Bilinmeyen YOLOX modeli: {name_or_path!r}. Seçenekler: {known}")

    target = models_dir / f"{spec.name}.onnx"
    if not target.is_file():
        download_file(spec.url, target, sha256=spec.sha256, progress=progress)
    return target


def download_file(
    url: str,
    target: Path,
    *,
    sha256: str | None = None,
    progress: ProgressCallback | None = None,
    chunk_size: int = 1 << 16,
) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    log.info("Model indiriliyor: %s", url)
    try:
        with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as fh:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while chunk := response.read(chunk_size):
                fh.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise ModelError(f"Model indirilemedi ({url}): {exc}") from exc

    if sha256 and digest.hexdigest() != sha256:
        partial.unlink(missing_ok=True)
        raise ModelError(f"İndirilen dosyanın doğrulaması başarısız: {url}")
    partial.replace(target)
    log.info("Model kaydedildi: %s", target)
    return target
