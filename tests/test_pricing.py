from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from plakatanima.core.formatting import format_duration, format_money
from plakatanima.core.pricing import DEFAULT_TARIFFS, TariffRule
from plakatanima.core.vehicle import VehicleType, vehicle_type_from_class_name

RULE = TariffRule(
    free_minutes=15,
    first_hour_fee=Decimal("60"),
    additional_hour_fee=Decimal("30"),
    daily_max_fee=Decimal("400"),
)


@pytest.mark.parametrize(
    ("minutes", "fee"),
    [
        (0, "0"),
        (15, "0"),  # ücretsiz süre dahil
        (16, "60"),
        (60, "60"),
        (61, "90"),
        (120, "90"),
        (121, "120"),
        (12 * 60, "390"),
        (13 * 60, "400"),  # günlük tavan
        (24 * 60, "400"),
        (24 * 60 + 1, "460"),  # 1 gün + yeni günün ilk saati
        (48 * 60 + 90, "890"),  # 2 gün + 2 saat
    ],
)
def test_fee_for_minutes(minutes, fee):
    assert RULE.fee_for_minutes(minutes) == Decimal(fee)


def test_partial_minutes_round_up():
    assert RULE.fee_for_minutes(15.2) == Decimal("60")


def test_no_daily_cap():
    rule = TariffRule(0, Decimal("10"), Decimal("10"), Decimal("0"))
    assert rule.fee_for_minutes(25 * 60) == Decimal("250")


def test_fee_between_datetimes():
    entry = datetime(2026, 1, 1, 8, 0)
    assert RULE.fee_between(entry, entry + timedelta(hours=2, minutes=5)) == Decimal("120")
    assert RULE.fee_for_duration(timedelta(minutes=-5)) == Decimal("0")


def test_every_vehicle_type_has_default_tariff():
    assert set(DEFAULT_TARIFFS) == set(VehicleType)


def test_vehicle_type_helpers():
    assert vehicle_type_from_class_name("Truck") is VehicleType.TRUCK
    assert vehicle_type_from_class_name("pickup-truck") is VehicleType.LIGHT_COMMERCIAL
    assert vehicle_type_from_class_name("person") is None
    assert VehicleType.parse("motosiklet") is VehicleType.MOTORCYCLE
    assert VehicleType.parse("uçak") is VehicleType.UNKNOWN
    assert VehicleType.parse(None) is VehicleType.UNKNOWN
    assert VehicleType.BUS.label == "Otobüs / Minibüs"


def test_formatting():
    assert format_duration(timedelta(minutes=45)) == "45 dk"
    assert format_duration(timedelta(hours=2, minutes=5)) == "2 sa 05 dk"
    assert format_duration(timedelta(days=1, minutes=3)) == "1 gün 0 sa 03 dk"
    assert format_money(Decimal("1234.5")) == "1.234,50 TL"
    assert format_money(None) == "0,00 TL"
