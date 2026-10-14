from __future__ import annotations

import pytest

from plakatanima.core.plate import (
    PROVINCES,
    clean_text,
    format_plate,
    is_valid_turkish_plate,
    normalize_plate,
    parse_plate,
)


def test_all_81_provinces_present():
    assert len(PROVINCES) == 81
    assert PROVINCES["34"] == "İstanbul"
    assert PROVINCES["81"] == "Düzce"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("34 ABC 123", "34ABC123"),
        ("34ABC12", "34ABC12"),
        ("06 AB 1234", "06AB1234"),
        ("06 AB 123", "06AB123"),
        ("35 A 1234", "35A1234"),
        ("35 A 12345", "35A12345"),
        ("34-abc-123", "34ABC123"),
        ("tr 34 abc 123", None),  # "TR" ülke kodu zaten OCR sonrası atılmış olmalı
    ],
)
def test_parse_valid_formats(raw, expected):
    parsed = parse_plate(raw)
    assert (parsed.text if parsed else None) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "00 ABC 123",  # il kodu yok
        "82 ABC 123",  # il kodu yok
        "34 ABCD 12",  # 4 harf
        "34 AB 12",  # çok kısa
        "34 ABC 1234",  # 3 harf + 4 rakam
        "34 A 123",  # 1 harf + 3 rakam
        "",
        "ABCDEFG",
    ],
)
def test_parse_rejects_invalid(raw):
    assert parse_plate(raw, allow_corrections=False) is None


@pytest.mark.parametrize(
    ("ocr", "expected", "corrections"),
    [
        ("34A8C123", "34ABC123", 1),  # 8 -> B
        ("3AABC123", "34ABC123", 1),  # A -> 4 (il kodu)
        ("O6AB1234", "06AB1234", 1),  # O -> 0
        ("34ABC1Z3", "34ABC123", 1),  # Z -> 2
        ("O6ABCI23", "06ABC123", 2),  # O -> 0, I -> 1
        ("06A5I234", "06A51234", 1),  # "06 AS 1234" (2 düzeltme) yerine en az düzeltme
        ("35BO123", "35BO123", 0),  # BO harfleri geçerli, düzeltme yok
    ],
)
def test_ocr_corrections(ocr, expected, corrections):
    parsed = parse_plate(ocr)
    assert parsed is not None
    assert parsed.text == expected
    assert parsed.corrections == corrections


def test_prefers_reading_with_fewest_corrections():
    # 8 karakter: "34 A B1234" (B->8, 1 düzeltme) yerine "34 AB 1234" (0 düzeltme)
    assert parse_plate("34AB1234").text == "34AB1234"


def test_no_corrections_when_disabled():
    assert parse_plate("34A8C123", allow_corrections=False) is None
    assert is_valid_turkish_plate("34 ABC 123")
    assert not is_valid_turkish_plate("34A8C123")


def test_turkish_characters_are_simplified():
    assert clean_text("34 şğü 12") == "34SGU12"
    assert normalize_plate("34 ışç 12") == "34ISC12"


def test_normalize_foreign_plates():
    assert normalize_plate("B-MW 1234") is None
    assert normalize_plate("B-MW 1234", turkish_only=False) == "BMW1234"
    assert normalize_plate("AB", turkish_only=False) is None


def test_format_plate():
    assert format_plate("34ABC123") == "34 ABC 123"
    assert format_plate("06A12345") == "06 A 12345"
    assert format_plate("BMW1234") == "BMW1234"
    parsed = parse_plate("34ABC123")
    assert parsed.province_name == "İstanbul"
