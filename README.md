# Plaka Tanıma Otopark Sistemi

Otoparklara giren ve çıkan araçların plakalarını kameradan okuyan, araçları
tipine göre (otomobil, motosiklet, kamyon, otobüs …) ayıran, giriş/çıkış
kayıtlarını veritabanında tutan ve ücretlendiren masaüstü uygulaması.

> Proje milestone'lar halinde geliştiriliyor; durum için [ROADMAP.md](ROADMAP.md).

## Kurulum

Python 3.11+ gerekir.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Kullanım

```bash
plakatanima config --show        # aktif ayarları ve dosya yollarını gösterir
```

Ayarlar ve veriler işletim sisteminin kullanıcı dizinlerinde tutulur.
Tüm dosyaları tek bir klasörde tutmak için (taşınabilir mod):

```bash
export PLAKATANIMA_HOME=./data
```

## Geliştirme

```bash
pytest -q
ruff check . && ruff format --check .
```

## Lisans

MIT — bkz. [LICENSE](LICENSE).
