"""Yapay plaka ve araç (arkadan görünüm) görüntüleri üretir.

Demo modunda kamera olmadan arayüzü denemek ve testlerde OCR'ı doğrulamak için kullanılır.
"""

from __future__ import annotations

from functools import lru_cache

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from plakatanima.core.plate import format_plate
from plakatanima.core.vehicle import VehicleType

_BOLD_FONTS = (
    "DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "arialbd.ttf",
    "Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)


@lru_cache(maxsize=32)
def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in _BOLD_FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def render_plate(text: str, width: int = 520, height: int = 112) -> np.ndarray:
    """Türk plakası görünümünde BGR görüntü (sol tarafta mavi 'TR' şeridi)."""
    img = Image.new("RGB", (width, height), (246, 246, 246))
    draw = ImageDraw.Draw(img)
    strip = int(height * 0.5)
    draw.rectangle((0, 0, strip, height), fill=(0, 56, 168))
    tr_font = _font(int(height * 0.24))
    draw.text((strip / 2, height * 0.78), "TR", font=tr_font, fill=(255, 255, 255), anchor="mm")

    label = format_plate(text)
    available = width - strip - int(width * 0.06)
    size = int(height * 0.78)
    font = _font(size)
    while size > 10 and draw.textlength(label, font=font) > available:
        size -= 2
        font = _font(size)
    center_x = strip + (width - strip) / 2
    draw.text((center_x, height / 2), label, font=font, fill=(15, 15, 15), anchor="mm")
    border = max(2, height // 28)
    draw.rectangle((0, 0, width - 1, height - 1), outline=(20, 20, 20), width=border)
    return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)


# (genişlik, yükseklik) — çerçeve genişliğine oranla, arkadan görünüm
_VEHICLE_SHAPES: dict[VehicleType, tuple[float, float]] = {
    VehicleType.MOTORCYCLE: (0.16, 0.42),
    VehicleType.CAR: (0.42, 0.40),
    VehicleType.LIGHT_COMMERCIAL: (0.46, 0.52),
    VehicleType.TRUCK: (0.56, 0.70),
    VehicleType.BUS: (0.58, 0.74),
    VehicleType.UNKNOWN: (0.42, 0.40),
}


def background(width: int = 1280, height: int = 720) -> np.ndarray:
    """Otopark girişi: asfalt, şerit çizgileri ve bariyer."""
    rows = np.linspace(70, 105, height, dtype=np.float32)[:, None, None]
    img = np.broadcast_to(rows, (height, width, 3)).astype(np.uint8).copy()
    horizon = int(height * 0.22)
    img[:horizon] = (150, 130, 110)  # duvar
    cv2.line(img, (0, horizon), (width, horizon), (60, 60, 60), 3)
    for x in range(-200, width + 200, 260):
        cv2.line(
            img, (width // 2 + (x - width // 2) // 4, horizon), (x, height), (190, 190, 190), 3
        )
    pole_x1, pole_x2 = int(width * 0.03), int(width * 0.055)
    arm_y1, arm_y2 = int(height * 0.12), int(height * 0.15)
    cv2.rectangle(img, (pole_x1, arm_y1), (pole_x2, int(height * 0.92)), (40, 40, 40), -1)
    stripe = max(int(width * 0.03), 4)
    for i, x in enumerate(range(pole_x2, int(width * 0.32), stripe)):
        color = (30, 30, 220) if i % 2 == 0 else (240, 240, 240)
        cv2.rectangle(img, (x, arm_y1), (x + stripe, arm_y2), color, -1)
    return img


def render_vehicle(
    frame: np.ndarray,
    plate_text: str,
    vehicle_type: VehicleType,
    *,
    center_x: float = 0.5,
    bottom_y: float = 0.95,
    scale: float = 1.0,
    color: tuple[int, int, int] = (160, 60, 40),
) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int]]:
    """Kareye arkadan görünen bir araç çizer. (araç kutusu, plaka kutusu) döndürür."""
    height, width = frame.shape[:2]
    rel_w, rel_h = _VEHICLE_SHAPES[vehicle_type]
    vw, vh = int(width * rel_w * scale), int(width * rel_h * scale * 0.75)
    x1 = int(width * center_x - vw / 2)
    y2 = int(height * bottom_y)
    y1 = y2 - vh
    x2 = x1 + vw
    dark = tuple(int(c * 0.55) for c in color)

    wheel_w, wheel_h = max(vw // 9, 6), max(vh // 9, 6)
    for wx in (x1 + vw // 12, x2 - vw // 12 - wheel_w):
        cv2.rectangle(frame, (wx, y2 - wheel_h // 2), (wx + wheel_w, y2), (25, 25, 25), -1)

    if vehicle_type is VehicleType.MOTORCYCLE:
        cv2.rectangle(frame, (x1 + vw // 3, y1), (x2 - vw // 3, y2 - wheel_h), color, -1)
        cv2.ellipse(frame, ((x1 + x2) // 2, y1), (vw // 3, vh // 8), 0, 180, 360, (40, 40, 40), -1)
        cv2.circle(frame, ((x1 + x2) // 2, y1 + vh // 4), max(vw // 10, 3), (30, 30, 230), -1)
    else:
        body_top = y1 + (vh // 3 if vehicle_type is VehicleType.CAR else vh // 12)
        cv2.rectangle(frame, (x1, body_top), (x2, y2 - wheel_h // 2), color, -1)
        if vehicle_type is VehicleType.CAR:
            roof = np.array([[x1 + vw // 8, body_top], [x1 + vw // 4, y1],
                             [x2 - vw // 4, y1], [x2 - vw // 8, body_top]])  # fmt: skip
            cv2.fillPoly(frame, [roof], color)
            inset = max(vw // 40, 2)
            window = roof + np.array([[inset, 0], [inset, inset], [-inset, inset], [-inset, 0]])
            cv2.fillPoly(frame, [window], dark)
        else:
            win_y2 = body_top + (y2 - body_top) // 3
            cv2.rectangle(
                frame, (x1 + vw // 12, body_top + vh // 20), (x2 - vw // 12, win_y2), dark, -1
            )
        light_y = y2 - vh // 3
        for lx in (x1 + vw // 30, x2 - vw // 30 - vw // 10):
            cv2.rectangle(
                frame, (lx, light_y), (lx + vw // 10, light_y + vh // 12), (30, 30, 220), -1
            )
        cv2.rectangle(frame, (x1, y2 - wheel_h // 2 - vh // 14), (x2, y2 - wheel_h // 2), dark, -1)

    plate_w = (
        int(min(vw * 0.55, width * 0.17 * scale))
        if vehicle_type is not (VehicleType.MOTORCYCLE)
        else int(vw * 0.7)
    )
    plate_h = max(int(plate_w * 0.215), 10)
    px1 = (x1 + x2) // 2 - plate_w // 2
    py2 = y2 - wheel_h // 2 - vh // 14 - 4
    py1 = py2 - plate_h
    plate = render_plate(plate_text, width=plate_w * 2, height=plate_h * 2)
    plate = cv2.resize(plate, (plate_w, plate_h), interpolation=cv2.INTER_AREA)
    fx1, fy1, fx2, fy2 = max(px1, 0), max(py1, 0), min(px1 + plate_w, width), min(py2, height)
    if fx2 > fx1 and fy2 > fy1:
        frame[fy1:fy2, fx1:fx2] = plate[fy1 - py1 : fy2 - py1, fx1 - px1 : fx2 - px1]
    vehicle_box = (max(x1, 0), max(y1 - vh // 8, 0), min(x2, width), min(y2, height))
    return vehicle_box, (px1, py1, px1 + plate_w, py2)
