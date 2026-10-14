"""Türkçe gösterim yardımcıları (süre, para, tarih)."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal


def format_duration(duration: timedelta) -> str:
    """``timedelta`` -> ``"2 gün 3 sa 05 dk"`` / ``"45 dk"``."""
    minutes = max(int(duration.total_seconds() // 60), 0)
    days, minutes = divmod(minutes, 24 * 60)
    hours, minutes = divmod(minutes, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days} gün")
    if hours or days:
        parts.append(f"{hours} sa")
    parts.append(f"{minutes:02d} dk" if parts else f"{minutes} dk")
    return " ".join(parts)


def format_money(amount: Decimal | float | int | None, currency: str = "TL") -> str:
    """``1234.5`` -> ``"1.234,50 TL"``."""
    value = Decimal(str(amount or 0)).quantize(Decimal("0.01"))
    text = f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{text} {currency}".strip()


def format_datetime(value: datetime | None, *, with_seconds: bool = False) -> str:
    if value is None:
        return "—"
    return value.strftime("%d.%m.%Y %H:%M:%S" if with_seconds else "%d.%m.%Y %H:%M")
