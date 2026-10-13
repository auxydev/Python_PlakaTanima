"""Araç tipleri ve nesne tespit modeli sınıflarının araç tiplerine eşlenmesi."""

from __future__ import annotations

from enum import StrEnum


class VehicleType(StrEnum):
    CAR = "otomobil"
    MOTORCYCLE = "motosiklet"
    # Kamyonet, panelvan, minibüs gibi hafif ticari araçlar
    LIGHT_COMMERCIAL = "hafif_ticari"
    TRUCK = "kamyon"
    BUS = "otobus"
    UNKNOWN = "bilinmiyor"

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def icon(self) -> str:
        """qtawesome (Material Design Icons) simge adı."""
        return _ICONS[self]

    @property
    def color(self) -> str:
        return _COLORS[self]

    @classmethod
    def parse(cls, value: str | VehicleType | None) -> VehicleType:
        if isinstance(value, VehicleType):
            return value
        try:
            return cls(value) if value else cls.UNKNOWN
        except ValueError:
            return cls.UNKNOWN


_LABELS = {
    VehicleType.CAR: "Otomobil",
    VehicleType.MOTORCYCLE: "Motosiklet",
    VehicleType.LIGHT_COMMERCIAL: "Hafif Ticari",
    VehicleType.TRUCK: "Kamyon",
    VehicleType.BUS: "Otobüs / Minibüs",
    VehicleType.UNKNOWN: "Bilinmiyor",
}

_ICONS = {
    VehicleType.CAR: "mdi6.car-side",
    VehicleType.MOTORCYCLE: "mdi6.motorbike",
    VehicleType.LIGHT_COMMERCIAL: "mdi6.van-utility",
    VehicleType.TRUCK: "mdi6.truck",
    VehicleType.BUS: "mdi6.bus",
    VehicleType.UNKNOWN: "mdi6.help-circle-outline",
}

_COLORS = {
    VehicleType.CAR: "#4C9AFF",
    VehicleType.MOTORCYCLE: "#FFAB00",
    VehicleType.LIGHT_COMMERCIAL: "#36B37E",
    VehicleType.TRUCK: "#FF5630",
    VehicleType.BUS: "#6554C0",
    VehicleType.UNKNOWN: "#8993A4",
}

# Nesne tespit modellerinin sınıf adları -> araç tipi. COCO ile eğitilmiş modeller
# car/motorcycle/bus/truck verir; özel eğitilmiş modeller diğer adları kullanabilir.
# Anahtarlar küçük harfli, "-" ve "_" yerine boşluk içeren biçimdedir.
CLASS_NAME_MAP: dict[str, VehicleType] = {
    "car": VehicleType.CAR,
    "otomobil": VehicleType.CAR,
    "motorcycle": VehicleType.MOTORCYCLE,
    "motorbike": VehicleType.MOTORCYCLE,
    "motosiklet": VehicleType.MOTORCYCLE,
    "scooter": VehicleType.MOTORCYCLE,
    "van": VehicleType.LIGHT_COMMERCIAL,
    "minivan": VehicleType.LIGHT_COMMERCIAL,
    "pickup": VehicleType.LIGHT_COMMERCIAL,
    "pickup truck": VehicleType.LIGHT_COMMERCIAL,
    "kamyonet": VehicleType.LIGHT_COMMERCIAL,
    "panelvan": VehicleType.LIGHT_COMMERCIAL,
    "hafif ticari": VehicleType.LIGHT_COMMERCIAL,
    "truck": VehicleType.TRUCK,
    "lorry": VehicleType.TRUCK,
    "kamyon": VehicleType.TRUCK,
    "bus": VehicleType.BUS,
    "minibus": VehicleType.BUS,
    "otobus": VehicleType.BUS,
}

# COCO-80 sınıf listesindeki araç sınıflarının indeksleri
COCO_VEHICLE_CLASSES: dict[int, VehicleType] = {
    2: VehicleType.CAR,
    3: VehicleType.MOTORCYCLE,
    5: VehicleType.BUS,
    7: VehicleType.TRUCK,
}


def vehicle_type_from_class_name(name: str) -> VehicleType | None:
    """Model sınıf adını araç tipine çevirir; araç değilse ``None``."""
    return CLASS_NAME_MAP.get(name.strip().lower().replace("-", " ").replace("_", " "))
