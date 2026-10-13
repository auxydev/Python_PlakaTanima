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
plakatanima config --show                    # aktif ayarları ve dosya yollarını gösterir
plakatanima status                           # doluluk ve günlük özet
plakatanima recognize araba.jpg -o sonuc.jpg # resimde araç + plaka tanıma
plakatanima recognize giris.mp4              # videodaki plakaları listeler
```

Modeller ilk kullanımda otomatik indirilir:

| Görev | Model | Lisans |
|---|---|---|
| Araç tespiti ve sınıflandırma | [YOLOX](https://github.com/Megvii-BaseDetection/YOLOX) (ONNX, COCO) | Apache-2.0 |
| Plaka tespiti + OCR | [fast-alpr](https://github.com/ankandrew/fast-alpr) (YOLOv9 + CCT) | MIT |
| (Opsiyonel) araç tespiti | [Ultralytics YOLO](https://github.com/ultralytics/ultralytics) — `pip install -e ".[yolo]"` | AGPL-3.0 |

Kendi eğittiğiniz bir Ultralytics modeli `van`, `minibus`, `pickup` gibi sınıflar
içeriyorsa bunlar otomatik olarak *Hafif Ticari* / *Otobüs-Minibüs* tiplerine eşlenir.

Ayarlar ve veriler işletim sisteminin kullanıcı dizinlerinde tutulur.
Tüm dosyaları tek bir klasörde tutmak için (taşınabilir mod):

```bash
export PLAKATANIMA_HOME=./data
```

## Geliştirme

```bash
pytest -q
ruff check . && ruff format --check .
PLAKATANIMA_MODEL_TESTS=1 pytest tests/test_models_integration.py   # gerçek modellerle
```

## Lisans

MIT — bkz. [LICENSE](LICENSE).
