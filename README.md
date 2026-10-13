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
plakatanima                                  # masaüstü uygulamasını açar
plakatanima gui --demo                       # kamera/model olmadan demo (önerilen ilk deneme)
plakatanima config --show                    # aktif ayarları ve dosya yollarını gösterir
plakatanima status                           # doluluk ve günlük özet
plakatanima recognize araba.jpg -o sonuc.jpg # resimde araç + plaka tanıma
plakatanima recognize giris.mp4              # videodaki plakaları listeler
plakatanima run                              # kameraları arayüzsüz çalıştırır
plakatanima run --demo                       # kamera/model olmadan simülasyon
```

Kamera kaynağı ayar dosyasında (`plakatanima config` yolu gösterir) tanımlanır:

```toml
[[cameras]]
name = "Giriş Kamerası"
source = "rtsp://kullanici:sifre@192.168.1.20:554/stream1"  # veya "0" (webcam), "video.mp4", "demo"
role = "giris"            # giris | cikis | giris_cikis (tek kamera ile ikisi birden)
process_fps = 4.0
roi = [0.0, 0.3, 1.0, 1.0] # isteğe bağlı: yalnızca karenin alt %70'i işlenir
```

Demo modu gerçek kayıtlardan ayrı bir veritabanı kullanır ve son 3 haftalık örnek
verilerle başlar.

### Arayüz

| Sayfa | İçerik |
|---|---|
| Gösterge Paneli | Canlı kameralar (araç/plaka kutuları), doluluk, bugünkü giriş/çıkış/tahsilat, son geçişler |
| İçerideki Araçlar | Otoparktaki araçlar, kalış süresi ve biriken ücret, tek tıkla çıkış |
| Geçiş Kayıtları | Tarih/plaka/tip/durum filtreleri, ödeme alma, giriş-çıkış fotoğrafları |
| Araçlar | Abone ve kara liste kayıtları, sahip bilgileri |
| Tarifeler | Araç tipine göre ücretlendirme ve ücret hesaplayıcı |
| Ayarlar | Otopark, kameralar (bağlantı testi), tanıma modelleri ve eşikler |

Kısayollar: **F2** manuel giriş, **F3** manuel çıkış, **Ctrl+1…6** sayfalar.

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
