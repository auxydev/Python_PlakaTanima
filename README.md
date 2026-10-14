# Plaka Tanıma Otopark Sistemi

Otoparklara giren ve çıkan araçların plakalarını kameradan okuyan, araçları tipine
göre (**otomobil, motosiklet, hafif ticari, kamyon, otobüs/minibüs**) ayıran,
giriş/çıkışları veritabanında tutan, ücretlendiren ve raporlayan masaüstü uygulaması.

![Gösterge paneli](docs/images/dashboard.jpg)

> Proje milestone'lar halinde geliştirildi; yapılanlar ve sıradakiler için
> [ROADMAP.md](ROADMAP.md).

## Özellikler

- **Plaka tanıma**: YOLOv9 plaka dedektörü + CCT OCR ([fast-alpr](https://github.com/ankandrew/fast-alpr), ONNX).
  Türk plaka formatı doğrulanır (il kodu 01–81, 1–3 harf, 2–5 rakam), OCR karışıklıkları
  (O↔0, I↔1, B↔8, S↔5 …) konuma göre düzeltilir, OCR'ın ülke tahmini sayesinde
  yabancı plakalar yanlışlıkla "düzeltilmez".
- **Araç sınıflandırma**: [YOLOX](https://github.com/Megvii-BaseDetection/YOLOX) (ONNX, Apache-2.0)
  ile araç tespiti; plaka, içinde bulunduğu araca eşlenir. İsteğe bağlı olarak kendi
  eğittiğiniz Ultralytics YOLO modeli kullanılabilir.
- **Kararlı okuma**: Araç kameranın önünden geçerken plaka birçok karede okunur, okumalar
  oylanır, plaka bir kez onaylanır; aynı araç beklerken tekrar kaydedilmez.
- **Otopark iş kuralları**: giriş/çıkış kameraları veya tek kamerayla ikisi birden,
  abone (ücretsiz), kara liste alarmı, kapasite uyarısı, çıkışı okunamayan araçların
  otomatik kapatılması, araç tipine göre tarife (ücretsiz süre, ilk saat, ek saat, günlük tavan).
- **Arayüz** (PySide6): canlı kamera görüntüleri ve tespit kutuları, doluluk, günlük özet,
  saatlik trafik grafiği, son geçişler, ödeme alma, manuel giriş/çıkış, geçiş fotoğrafları.
- **Raporlar**: günlük tahsilat, giriş/çıkış, araç tipi ve ödeme yöntemi dağılımı,
  saatlik yoğunluk; **Excel / CSV** dışa aktarma.
- **Yönetim**: kullanıcı girişi, yönetici/operatör rolleri, otomatik günlük veritabanı
  yedeği, eski görüntülerin temizlenmesi.
- **Kamera kaynakları**: USB/webcam, IP kamera (RTSP/HTTP), video dosyası; bağlantı
  koparsa otomatik yeniden bağlanma. Kamera olmadan denemek için **demo modu**.

## Hızlı başlangıç

Python 3.11+ gerekir.

```bash
git clone https://github.com/auxydev/Python_PlakaTanima.git
cd Python_PlakaTanima
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .

plakatanima gui --demo             # kamera ve model gerektirmeyen demo
plakatanima                        # gerçek kurulum (ilk giriş: admin / admin)
```

Demo modu gerçek kayıtlardan ayrı bir veritabanı kullanır, son üç haftalık örnek
verilerle açılır ve iki sanal kamerada araç trafiği simüle eder.

İlk gerçek çalıştırmada tanıma modelleri (~45 MB) otomatik indirilir. NVIDIA GPU
kullanmak için `pip install onnxruntime-gpu` yeterlidir; Ayarlar › Tanıma › Donanım.

## Kamera kurulumu

Kameralar arayüzden (Ayarlar › Kameralar, *Bağlantıyı Test Et* ile) veya ayar
dosyasından (`plakatanima config` yolu gösterir) tanımlanır:

```toml
[[cameras]]
name = "Giriş Kamerası"
source = "rtsp://kullanici:sifre@192.168.1.20:554/stream1"  # "0" (webcam), "giris.mp4", "demo"
role = "giris"              # giris | cikis | giris_cikis (tek kamerayla ikisi birden)
process_fps = 4.0           # saniyede analiz edilen kare
roi = [0.0, 0.3, 1.0, 1.0]  # isteğe bağlı: yalnızca karenin alt %70'i işlenir

[[cameras]]
name = "Çıkış Kamerası"
source = "rtsp://kullanici:sifre@192.168.1.21:554/stream1"
role = "cikis"
```

İpuçları: plaka karede en az ~100 piksel genişliğinde olmalı; kamerayı araç yoluna
dar açıyla yerleştirin; gece için IR destekli kamera kullanın; ilgi alanı (ROI) hem
hızı hem doğruluğu artırır.

## Komut satırı

| Komut | Açıklama |
|---|---|
| `plakatanima` / `plakatanima gui [--demo]` | Masaüstü uygulaması |
| `plakatanima run [--demo]` | Kameraları arayüzsüz çalıştırır (sunucu modu) |
| `plakatanima recognize resim.jpg -o sonuc.jpg` | Resim/video üzerinde araç + plaka tanıma |
| `plakatanima status` | Doluluk ve günlük özet |
| `plakatanima export rapor.xlsx --start 01.10.2026` | Geçişleri Excel/CSV'ye aktarır |
| `plakatanima user add kasa --role operator` | Kullanıcı ekler (`list`, `passwd`, `delete`) |
| `plakatanima user passwd admin` | Unutulan parolayı sıfırlar |
| `plakatanima backup` | Veritabanını yedekler |
| `plakatanima config --show` | Ayarları ve dosya yollarını gösterir |

Tüm dosyaları tek klasörde tutmak için (taşınabilir mod): `PLAKATANIMA_HOME=./veri plakatanima`

## Arayüz

| Sayfa | İçerik |
|---|---|
| Gösterge Paneli | Canlı kameralar, doluluk, bugünkü giriş/çıkış/tahsilat, saatlik trafik, son geçişler |
| İçerideki Araçlar | Otoparktaki araçlar, kalış süresi ve biriken ücret, tek tıkla çıkış |
| Geçiş Kayıtları | Tarih/plaka/tip/durum filtreleri, ödeme alma, giriş-çıkış fotoğrafları |
| Araçlar | Abone ve kara liste kayıtları, sahip bilgileri |
| Raporlar | Dönem özeti, grafikler, Excel/CSV dışa aktarma |
| Tarifeler* | Araç tipine göre ücretlendirme ve ücret hesaplayıcı |
| Kullanıcılar* | Yönetici/operatör hesapları, parola sıfırlama |
| Ayarlar* | Otopark, kameralar, tanıma modelleri, bakım (yedek, temizlik) |

\* Yalnızca yönetici. Kısayollar: **F2** manuel giriş, **F3** manuel çıkış, **Ctrl+1…8** sayfalar.

![Raporlar](docs/images/raporlar.jpg)

## Nasıl çalışır

```mermaid
flowchart LR
    K[Kamera / video] -->|kareler| Y[Yakalama iş parçacığı]
    Y -->|en son kare| A[Analiz iş parçacığı]
    A --> V[YOLOX<br/>araç tespiti + tipi]
    A --> P[fast-alpr<br/>plaka tespiti + OCR]
    V & P --> E[Plaka → araç eşleme<br/>TR formatı + düzeltme]
    E --> O[Çoklu kare oylama<br/>tekrar engelleme]
    O -->|onaylı plaka + fotoğraf| S[ParkingService<br/>giriş / çıkış / ücret]
    S --> D[(SQLite / PostgreSQL)]
    S --> G[Arayüz: panel, uyarılar]
```

## Proje yapısı

```
src/plakatanima/
├── core/          # plaka formatı, araç tipleri, ücret hesabı (bağımsız, test edilebilir)
├── db/            # SQLAlchemy modelleri ve bağlantı
├── services/      # giriş/çıkış kuralları, araç/tarife, raporlar, kullanıcılar, yedek
├── recognition/   # araç dedektörü, plaka okuyucu, analiz hattı, oylama, model indirme
├── camera/        # görüntü kaynakları, kamera iş parçacıkları, anlık görüntüler
├── demo/          # simülasyon kaynağı ve örnek veri
├── gui/           # PySide6 arayüzü (sayfalar, bileşenler, diyaloglar)
├── config.py      # TOML ayarları (pydantic)
└── cli.py         # komut satırı
```

## Geliştirme

```bash
pip install -e ".[dev]"
pytest -q                                   # birim + arayüz testleri (ekransız çalışır)
ruff check . && ruff format --check .
PLAKATANIMA_MODEL_TESTS=1 pytest tests/test_models_integration.py   # gerçek modellerle
```

## Bilinen kısıtlar

- Varsayılan araç modeli COCO ile eğitilmiştir: *kamyonet/panelvan* gibi hafif ticari
  araçları ayrı bir sınıf olarak tanımaz (otomobil veya kamyon olarak görür). Kayıtlı
  araçlarda kayıttaki tip kullanılır; geçiş ayrıntısından tip düzeltilebilir.
  `van`, `minibus`, `pickup` sınıfları içeren özel bir Ultralytics modeli
  (`pip install -e ".[yolo]"`) bu tipleri doğrudan ayırır.
- Resmi, askeri ve diplomatik plaka biçimleri Türk formatı olarak doğrulanmaz;
  "Yalnızca Türk plaka formatı" ayarı kapatılarak kabul edilebilir.

## Lisans

MIT — bkz. [LICENSE](LICENSE).

Kullanılan modeller: YOLOX (Apache-2.0), fast-alpr / open-image-models / fast-plate-ocr (MIT).
Opsiyonel Ultralytics paketi **AGPL-3.0** lisanslıdır; dağıtım yapacaksanız lisans
koşullarını göz önünde bulundurun.
