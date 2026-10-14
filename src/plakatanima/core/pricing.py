"""Otopark ücret hesaplama.

Kural:
  * Kalış süresi ``free_minutes`` veya daha kısaysa ücret alınmaz.
  * Her tam 24 saat için günlük tavan (``daily_max_fee``) uygulanır.
  * Kalan süre saat bloklarına yuvarlanır: ilk saat ``first_hour_fee``, sonraki
    her başlayan saat ``additional_hour_fee``. Bu tutar da günlük tavanı aşamaz.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from plakatanima.core.vehicle import VehicleType

MINUTES_PER_DAY = 24 * 60
_CENTS = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class TariffRule:
    free_minutes: int = 15
    first_hour_fee: Decimal = Decimal("60")
    additional_hour_fee: Decimal = Decimal("30")
    # 0 = günlük tavan yok
    daily_max_fee: Decimal = Decimal("400")

    def _day_fee(self, minutes: int) -> Decimal:
        """24 saati aşmayan bir sürenin ücreti (günlük tavan uygulanmış)."""
        if minutes <= 0:
            return Decimal(0)
        hours = math.ceil(minutes / 60)
        fee = self.first_hour_fee + (hours - 1) * self.additional_hour_fee
        if self.daily_max_fee > 0:
            fee = min(fee, self.daily_max_fee)
        return fee

    def fee_for_minutes(self, minutes: float) -> Decimal:
        total = math.ceil(max(minutes, 0))
        if total <= self.free_minutes:
            return Decimal(0)
        days, rest = divmod(total, MINUTES_PER_DAY)
        fee = days * self._day_fee(MINUTES_PER_DAY) + self._day_fee(rest)
        return fee.quantize(_CENTS, rounding=ROUND_HALF_UP)

    def fee_for_duration(self, duration: timedelta) -> Decimal:
        return self.fee_for_minutes(duration.total_seconds() / 60)

    def fee_between(self, entry: datetime, exit_: datetime) -> Decimal:
        return self.fee_for_duration(exit_ - entry)


def _rule(free: int, first: str, extra: str, daily: str) -> TariffRule:
    return TariffRule(free, Decimal(first), Decimal(extra), Decimal(daily))


# İlk kurulumda veritabanına yazılan örnek tarifeler (arayüzden değiştirilebilir).
DEFAULT_TARIFFS: dict[VehicleType, TariffRule] = {
    VehicleType.CAR: _rule(15, "60", "30", "400"),
    VehicleType.MOTORCYCLE: _rule(15, "30", "15", "150"),
    VehicleType.LIGHT_COMMERCIAL: _rule(15, "80", "40", "500"),
    VehicleType.TRUCK: _rule(15, "150", "75", "900"),
    VehicleType.BUS: _rule(15, "150", "75", "900"),
    VehicleType.UNKNOWN: _rule(15, "60", "30", "400"),
}
