from __future__ import annotations

from plakatanima.core.vehicle import VehicleType
from plakatanima.recognition.tracker import PlateVoter, levenshtein
from plakatanima.recognition.types import BBox, PlateRead, VehicleDetection

BOX = BBox(100, 300, 200, 330)


def read(text, conf=0.9, vehicle_type=None, bbox=BOX):
    vehicle = VehicleDetection(BBox(0, 0, 400, 400), vehicle_type, 0.8) if vehicle_type else None
    return PlateRead(bbox=bbox, text=text, raw_text=text, confidence=conf, vehicle=vehicle)


def test_levenshtein():
    assert levenshtein("34ABC123", "34ABC123") == 0
    assert levenshtein("34ABC123", "34ABC128") == 1
    assert levenshtein("34ABC123", "34ABC12") == 1
    assert levenshtein("", "abc") == 3


def test_confirms_after_min_hits_with_majority_text():
    voter = PlateVoter(min_hits=3, track_timeout=2.0, cooldown=30)
    assert voter.update([read("34ABC123", 0.9, VehicleType.CAR)], payload="f1", now=0.0) == []
    assert voter.update([read("34ABC128", 0.5)], payload="f2", now=0.3) == []
    confirmed = voter.update([read("34ABC123", 0.95, VehicleType.CAR)], payload="f3", now=0.6)
    assert len(confirmed) == 1
    result = confirmed[0]
    assert result.plate == "34ABC123"
    assert result.hits == 3
    assert result.vehicle_type is VehicleType.CAR
    assert result.payload == "f3"  # en yüksek güvenli okumanın karesi
    assert abs(result.confidence - 0.925) < 1e-9
    assert result.raw_texts == ["34ABC123", "34ABC128", "34ABC123"]


def test_plate_staying_in_view_is_not_reconfirmed():
    voter = PlateVoter(min_hits=2, track_timeout=1.0, cooldown=5)
    t = 0.0
    emitted = []
    for _ in range(40):  # 40 * 0.25 sn = 10 sn boyunca kamera önünde
        emitted += voter.update([read("06AB1234")], now=t)
        t += 0.25
    assert [c.plate for c in emitted] == ["06AB1234"]


def test_cooldown_then_reconfirm():
    voter = PlateVoter(min_hits=1, track_timeout=1.0, cooldown=10)
    assert len(voter.update([read("06AB1234")], now=0.0)) == 1
    # İz zaman aşımına uğradı ama bekleme süresi dolmadı
    assert voter.update([read("06AB1234")], now=5.0) == []
    # Son görülmeden itibaren bekleme süresi doldu
    assert len(voter.update([read("06AB1234")], now=16.0)) == 1


def test_different_plates_get_separate_tracks():
    voter = PlateVoter(min_hits=2, track_timeout=2.0, cooldown=10)
    other_box = BBox(600, 300, 700, 330)
    voter.update([read("34ABC123"), read("35XY987", bbox=other_box)], now=0.0)
    confirmed = voter.update([read("34ABC123"), read("35XY987", bbox=other_box)], now=0.2)
    assert sorted(c.plate for c in confirmed) == ["34ABC123", "35XY987"]


def test_unconfirmed_track_expires():
    voter = PlateVoter(min_hits=2, track_timeout=1.0, cooldown=10)
    voter.update([read("34ABC123")], now=0.0)
    assert voter.update([read("34ABC123")], now=3.0) == []
    assert voter.active_tracks == 1
    assert len(voter.update([read("34ABC123")], now=3.5)) == 1


def test_unknown_vehicle_type_when_no_vehicle_seen():
    voter = PlateVoter(min_hits=1)
    assert voter.update([read("34ABC123")], now=0.0)[0].vehicle_type is VehicleType.UNKNOWN
