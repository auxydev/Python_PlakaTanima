"""Ardışık karelerdeki plaka okumalarını birleştirip tek bir onaylı okuma üretir.

Tek bir karedeki OCR sonucu hatalı olabilir; araç kameranın önünden geçerken
plaka birçok kez okunur. :class:`PlateVoter` birbirine benzeyen okumaları
(aynı metin veya tek karakter farkı) aynı "iz"de toplar, iz yeterli sayıda
okumaya ulaşınca en güçlü metni seçer ve plakayı bir kez onaylar. Aynı plaka
kameranın önünde kaldıkça veya bekleme süresi dolmadan tekrar görülürse yeniden
onaylanmaz.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from plakatanima.core.vehicle import VehicleType
from plakatanima.recognition.types import PlateRead


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


@dataclass(slots=True)
class ConfirmedPlate:
    plate: str
    confidence: float
    vehicle_type: VehicleType
    hits: int
    raw_texts: list[str]
    best_read: PlateRead
    # Okumanın yapıldığı kare vb. (çağıran tarafından verilir; anlık görüntü için)
    payload: Any = None


@dataclass(slots=True)
class _Track:
    first_seen: float
    last_seen: float
    reads: list[PlateRead] = field(default_factory=list)
    text_scores: dict[str, float] = field(default_factory=dict)
    best_read: PlateRead | None = None
    best_payload: Any = None
    confirmed_text: str | None = None

    @property
    def leader(self) -> str:
        return max(self.text_scores, key=self.text_scores.__getitem__)

    def add(self, read: PlateRead, payload: Any, now: float) -> None:
        self.reads.append(read)
        self.text_scores[read.text] = self.text_scores.get(read.text, 0.0) + read.confidence
        self.last_seen = now
        if self.best_read is None or read.confidence >= self.best_read.confidence:
            self.best_read = read
            self.best_payload = payload

    def similarity(self, read: PlateRead) -> int | None:
        """Okumanın bu ize uzaklığı; aynı araca ait sayılmıyorsa ``None``."""
        distance = min(levenshtein(read.text, text) for text in self.text_scores)
        last_bbox = self.reads[-1].bbox
        if distance <= 1 or (distance <= 2 and read.bbox.iou(last_bbox) >= 0.3):
            return distance
        return None


def dominant_vehicle_type(reads: list[PlateRead]) -> VehicleType:
    """Okumalardaki araç tiplerinin güven ağırlıklı çoğunluğu."""
    votes: dict[VehicleType, float] = {}
    for read in reads:
        if read.vehicle is not None:
            vtype = read.vehicle.vehicle_type
            votes[vtype] = votes.get(vtype, 0.0) + read.vehicle.confidence
    return max(votes, key=votes.__getitem__) if votes else VehicleType.UNKNOWN


class PlateVoter:
    def __init__(
        self,
        *,
        min_hits: int = 3,
        track_timeout: float = 2.5,
        cooldown: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.min_hits = min_hits
        self.track_timeout = track_timeout
        self.cooldown = cooldown
        self._clock = clock
        self._tracks: list[_Track] = []
        # plaka -> en son görüldüğü an (onaylandıktan sonra)
        self._recent: dict[str, float] = {}

    @property
    def active_tracks(self) -> int:
        return len(self._tracks)

    def reset(self) -> None:
        self._tracks.clear()
        self._recent.clear()

    def update(
        self, reads: list[PlateRead], payload: Any = None, now: float | None = None
    ) -> list[ConfirmedPlate]:
        now = self._clock() if now is None else now
        self._expire(now)

        for read in reads:
            track = self._find_track(read)
            if track is None:
                track = _Track(first_seen=now, last_seen=now)
                self._tracks.append(track)
            track.add(read, payload, now)
            if track.confirmed_text is not None:
                # Araç hâlâ kamera önünde: bekleme süresini uzat.
                self._recent[track.confirmed_text] = now

        confirmed: list[ConfirmedPlate] = []
        for track in self._tracks:
            if track.confirmed_text is not None or len(track.reads) < self.min_hits:
                continue
            text = track.leader
            track.confirmed_text = text
            last = self._recent.get(text)
            self._recent[text] = now
            if last is not None and now - last < self.cooldown:
                continue
            confirmed.append(self._result(track, text))
        return confirmed

    def _find_track(self, read: PlateRead) -> _Track | None:
        best: tuple[int, _Track] | None = None
        for track in self._tracks:
            distance = track.similarity(read)
            if distance is not None and (best is None or distance < best[0]):
                best = (distance, track)
        return best[1] if best else None

    def _expire(self, now: float) -> None:
        self._tracks = [t for t in self._tracks if now - t.last_seen <= self.track_timeout]
        horizon = max(self.cooldown, self.track_timeout)
        self._recent = {p: t for p, t in self._recent.items() if now - t < horizon}

    @staticmethod
    def _result(track: _Track, text: str) -> ConfirmedPlate:
        matching = [r for r in track.reads if r.text == text]
        best = max(matching, key=lambda r: r.confidence)
        return ConfirmedPlate(
            plate=text,
            confidence=sum(r.confidence for r in matching) / len(matching),
            vehicle_type=dominant_vehicle_type(track.reads),
            hits=len(track.reads),
            raw_texts=[r.raw_text for r in track.reads],
            best_read=best,
            # En güvenilir okumanın yapıldığı kare (metni farklı olsa da aynı aracı gösterir)
            payload=track.best_payload,
        )
