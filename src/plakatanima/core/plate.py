"""Türk plakası ayrıştırma, doğrulama ve OCR hatası düzeltme.

Standart sivil plaka: ``İl kodu (01-81) + 1-3 harf + 2-5 rakam``

=======  ==========  =====================
Harf     Rakam       Örnek
=======  ==========  =====================
1        4-5         ``34 A 1234``
2        3-4         ``06 AB 123``
3        2-3         ``35 ABC 12``
=======  ==========  =====================

OCR modelleri benzer görünen karakterleri karıştırabilir (``O``/``0``, ``I``/``1``,
``B``/``8`` ...). Plakadaki her karakterin harf mi rakam mı olması gerektiği
konumundan bilindiği için bu hatalar en az değişiklikle düzeltilebilir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# (harf sayısı, en az rakam, en çok rakam). Format değişirse burası güncellenir.
PLATE_FORMATS: tuple[tuple[int, int, int], ...] = ((1, 4, 5), (2, 3, 4), (3, 2, 3))

PROVINCES: dict[str, str] = {
    "01": "Adana", "02": "Adıyaman", "03": "Afyonkarahisar", "04": "Ağrı", "05": "Amasya",
    "06": "Ankara", "07": "Antalya", "08": "Artvin", "09": "Aydın", "10": "Balıkesir",
    "11": "Bilecik", "12": "Bingöl", "13": "Bitlis", "14": "Bolu", "15": "Burdur",
    "16": "Bursa", "17": "Çanakkale", "18": "Çankırı", "19": "Çorum", "20": "Denizli",
    "21": "Diyarbakır", "22": "Edirne", "23": "Elazığ", "24": "Erzincan", "25": "Erzurum",
    "26": "Eskişehir", "27": "Gaziantep", "28": "Giresun", "29": "Gümüşhane", "30": "Hakkari",
    "31": "Hatay", "32": "Isparta", "33": "Mersin", "34": "İstanbul", "35": "İzmir",
    "36": "Kars", "37": "Kastamonu", "38": "Kayseri", "39": "Kırklareli", "40": "Kırşehir",
    "41": "Kocaeli", "42": "Konya", "43": "Kütahya", "44": "Malatya", "45": "Manisa",
    "46": "Kahramanmaraş", "47": "Mardin", "48": "Muğla", "49": "Muş", "50": "Nevşehir",
    "51": "Niğde", "52": "Ordu", "53": "Rize", "54": "Sakarya", "55": "Samsun",
    "56": "Siirt", "57": "Sinop", "58": "Sivas", "59": "Tekirdağ", "60": "Tokat",
    "61": "Trabzon", "62": "Tunceli", "63": "Şanlıurfa", "64": "Uşak", "65": "Van",
    "66": "Yozgat", "67": "Zonguldak", "68": "Aksaray", "69": "Bayburt", "70": "Karaman",
    "71": "Kırıkkale", "72": "Batman", "73": "Şırnak", "74": "Bartın", "75": "Ardahan",
    "76": "Iğdır", "77": "Yalova", "78": "Karabük", "79": "Kilis", "80": "Osmaniye",
    "81": "Düzce",
}  # fmt: skip

# Rakam olması gereken konumda okunan harf -> muhtemel rakam
_AS_DIGIT = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "J": "1", "A": "4",
             "Z": "2", "S": "5", "B": "8", "G": "6", "T": "7"}  # fmt: skip
# Harf olması gereken konumda okunan rakam -> muhtemel harf
_AS_LETTER = {"0": "O", "1": "I", "2": "Z", "4": "A", "5": "S", "6": "G", "7": "T", "8": "B"}

_TURKISH_TO_ASCII = str.maketrans("ÇĞİÖŞÜçğıöşü", "CGIOSUcgiosu")
_NON_ALNUM = re.compile(r"[^A-Z0-9]")

MIN_PLATE_LENGTH = 7
MAX_PLATE_LENGTH = 8
# Türk formatına uymayan (yabancı vb.) plakalar için kabul edilen uzunluk aralığı
FOREIGN_MIN_LENGTH = 4
FOREIGN_MAX_LENGTH = 10


@dataclass(frozen=True, slots=True)
class ParsedPlate:
    province: str
    letters: str
    digits: str
    corrections: int = 0

    @property
    def text(self) -> str:
        """Veritabanında saklanan biçim: ``34ABC123``."""
        return f"{self.province}{self.letters}{self.digits}"

    @property
    def formatted(self) -> str:
        """Görüntülenen biçim: ``34 ABC 123``."""
        return f"{self.province} {self.letters} {self.digits}"

    @property
    def province_name(self) -> str:
        return PROVINCES.get(self.province, "")


def clean_text(raw: str) -> str:
    """Büyük harfe çevirir, Türkçe karakterleri sadeleştirir, harf/rakam dışını atar."""
    return _NON_ALNUM.sub("", raw.translate(_TURKISH_TO_ASCII).upper())


def _convert(segment: str, *, digits: bool, allow: bool) -> tuple[str, int] | None:
    out: list[str] = []
    cost = 0
    for ch in segment:
        ok = ch.isdigit() if digits else ch.isalpha()
        if ok:
            out.append(ch)
            continue
        if not allow:
            return None
        mapped = (_AS_DIGIT if digits else _AS_LETTER).get(ch)
        if mapped is None:
            return None
        out.append(mapped)
        cost += 1
    return "".join(out), cost


def parse_plate(
    raw: str,
    *,
    allow_corrections: bool = True,
    max_corrections: int | None = None,
) -> ParsedPlate | None:
    """Metni Türk plakası olarak ayrıştırır; uymuyorsa ``None`` döner.

    ``allow_corrections`` açıkken OCR karışıklıkları en az değişiklikle düzeltilir;
    birden çok olası okuma varsa en az düzeltme gerektiren seçilir. ``max_corrections``
    verilirse daha fazla düzeltme gerektiren okumalar reddedilir.
    """
    text = clean_text(raw)
    if not MIN_PLATE_LENGTH <= len(text) <= MAX_PLATE_LENGTH:
        return None

    province = _convert(text[:2], digits=True, allow=allow_corrections)
    if province is None or province[0] not in PROVINCES:
        return None

    best: ParsedPlate | None = None
    for n_letters, min_digits, max_digits in PLATE_FORMATS:
        n_digits = len(text) - 2 - n_letters
        if not min_digits <= n_digits <= max_digits:
            continue
        letters = _convert(text[2 : 2 + n_letters], digits=False, allow=allow_corrections)
        digits = _convert(text[2 + n_letters :], digits=True, allow=allow_corrections)
        if letters is None or digits is None:
            continue
        candidate = ParsedPlate(
            province=province[0],
            letters=letters[0],
            digits=digits[0],
            corrections=province[1] + letters[1] + digits[1],
        )
        if max_corrections is not None and candidate.corrections > max_corrections:
            continue
        if best is None or candidate.corrections < best.corrections:
            best = candidate
    return best


def is_valid_turkish_plate(raw: str) -> bool:
    """Metin düzeltme gerektirmeden geçerli bir Türk plakası mı?"""
    return parse_plate(raw, allow_corrections=False) is not None


def normalize_plate(
    raw: str,
    *,
    turkish_only: bool = True,
    allow_corrections: bool = True,
    max_corrections: int | None = 2,
) -> str | None:
    """Plakayı saklama biçimine (``34ABC123``) getirir.

    Türk formatına uymayan metinler ``turkish_only`` kapalıysa makul uzunluktaysa
    temizlenmiş haliyle kabul edilir (yabancı plakalar), aksi halde ``None`` döner.
    """
    parsed = parse_plate(raw, allow_corrections=allow_corrections, max_corrections=max_corrections)
    if parsed is not None:
        return parsed.text
    if turkish_only:
        return None
    text = clean_text(raw)
    if FOREIGN_MIN_LENGTH <= len(text) <= FOREIGN_MAX_LENGTH:
        return text
    return None


def format_plate(plate: str) -> str:
    """Saklanan plakayı okunaklı biçimde gösterir (``34ABC123`` -> ``34 ABC 123``)."""
    parsed = parse_plate(plate, allow_corrections=False)
    return parsed.formatted if parsed else plate
