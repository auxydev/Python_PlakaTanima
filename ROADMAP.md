# Yol Haritası (Milestone'lar)

Proje küçük, her biri kendi başına çalışan ve test edilen adımlarla ilerler.
Her milestone ayrı bir commit olarak tamamlanır.

## M0 — Proje iskeleti ✅
- [x] `pyproject.toml`, `src/` düzeni, `plakatanima` komutu
- [x] TOML ayar dosyası (pydantic doğrulamalı), taşınabilir mod (`PLAKATANIMA_HOME`)
- [x] Konsol + dönen dosya logları
- [x] Ruff + pytest, GitHub Actions CI (Python 3.11 ve 3.13)

## M1 — Çekirdek alan modeli ✅
- [x] Türk plaka formatı doğrulama ve OCR hatalarını düzeltme (O↔0, I↔1, B↔8 …)
- [x] Araç tipleri (otomobil, motosiklet, hafif ticari, kamyon, otobüs)
- [x] Tarife ve ücret hesaplama (ücretsiz süre, ilk saat, ek saat, günlük tavan)

## M2 — Veritabanı ve servis katmanı ✅
- [x] SQLAlchemy 2 modelleri: araç kaydı, park oturumu, tarife, olay günlüğü, kullanıcı
- [x] Giriş/çıkış iş kuralları: tekrar okuma koruması, abone, kara liste, doluluk
- [x] Tek kamerayla giriş+çıkış, çıkışı okunamayan araçların otomatik kapatılması
- [x] İstatistikler (içerideki araç, günlük giriş/çıkış, tahsilat, tip dağılımı)
- [x] `plakatanima init-db`, `plakatanima status`

## M3 — Tanıma motoru ✅
- [x] Araç tespiti + sınıflandırma (YOLOX ONNX, SHA-256 doğrulamalı indirme; opsiyonel Ultralytics YOLO)
- [x] Plaka tespiti + OCR (fast-alpr, ONNX); OCR'ın ülke tahmini ile yabancı plakaların ayrılması
- [x] Plakayı araca eşleme, çoklu kare oylama ve tekrar engelleme
- [x] `plakatanima recognize` ile resim/video üzerinde deneme

## M4 — Kamera ve demo altyapısı ✅
- [x] Webcam / RTSP / video dosyası kaynakları, otomatik yeniden bağlanma
- [x] Kamera başına yakalama + analiz iş parçacıkları (IP kamerada gecikme birikmez)
- [x] Onaylanan geçişlerin anlık görüntüsü, saklama süresi dolanların temizliği
- [x] Kamera ve model olmadan denemek için demo (simülasyon) modu, örnek geçmiş veri
- [x] `plakatanima run` ile arayüzsüz (sunucu) çalışma

## M5 — Masaüstü arayüz (PySide6) ✅
- [x] Koyu/açık tema, kenar menülü ana pencere, Türkçe yerel ayar, kısayollar
- [x] Gösterge paneli: canlı kameralar (tespit kutuları), son geçişler, doluluk ve günlük kartlar
- [x] İçerideki araçlar (anlık süre/ücret), geçiş kayıtları (filtreli), araçlar, tarifeler, ayarlar
- [x] Manuel giriş/çıkış, ödeme alma (indirim), geçiş detayı (fotoğraflar), kara liste alarmı
- [x] Kamera bağlantı testi, ayarlar değişince kameraların yeniden başlatılması

## M6 — Raporlama ve yönetim ✅
- [x] Grafikli raporlar (günlük tahsilat, giriş/çıkış, araç tipi, ödeme yöntemi, saatlik yoğunluk)
- [x] Gösterge panelinde bugünün saatlik trafiği; renk körlüğüne karşı doğrulanmış palet
- [x] Excel (özet sayfalı) / CSV dışa aktarma — arayüz ve `plakatanima export`
- [x] Kullanıcı girişi, yönetici/operatör rolleri, ilk girişte parola değişikliği (scrypt)
- [x] Otomatik günlük veritabanı yedeği, bakım sekmesi, `plakatanima backup` / `user`

## M7 — Donanım entegrasyonu (planlanan)
- [ ] Bariyer/röle kontrolü (HTTP röle kartları, Modbus, seri port, Raspberry Pi GPIO)
- [ ] Kara listedeki araçta bariyerin açılmaması, abonelerde otomatik açılma
- [ ] Giriş tabelası için boş yer sayısı çıktısı (LED panel / HTTP)

## M8 — Web ve uzaktan erişim (planlanan)
- [ ] REST API (FastAPI): geçişler, doluluk, araç kayıtları
- [ ] Tarayıcıdan izleme paneli, telefon bildirimleri (kara liste, doluluk)
- [ ] Birden fazla otopark / şube, merkezi PostgreSQL

## M9 — Model iyileştirme (planlanan)
- [ ] Türk plakalarıyla OCR ince ayarı (fine-tuning) ve doğruluk ölçüm seti
- [ ] Hafif ticari / minibüs / panelvan sınıflarını içeren özel araç modeli
- [ ] Gece ve IR görüntüleri için ayarlar, araç rengi tespiti

## M10 — Dağıtım (planlanan)
- [ ] Windows kurulum paketi (PyInstaller), Docker imajı (sunucu modu)
- [ ] Veritabanı şema göçleri (Alembic)
