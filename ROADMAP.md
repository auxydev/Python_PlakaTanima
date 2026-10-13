# Yol Haritası (Milestone'lar)

Proje küçük, her biri kendi başına çalışan ve test edilen adımlarla ilerler.
Her milestone ayrı bir commit (veya commit grubu) olarak tamamlanır.

## M0 — Proje iskeleti ✅
- [x] `pyproject.toml`, `src/` düzeni, `plakatanima` komutu
- [x] TOML ayar dosyası (pydantic doğrulamalı), taşınabilir mod (`PLAKATANIMA_HOME`)
- [x] Konsol + dönen dosya logları
- [x] Ruff + pytest, GitHub Actions CI

## M1 — Çekirdek alan modeli ✅
- [x] Türk plaka formatı doğrulama ve OCR hatalarını düzeltme (O↔0, I↔1, B↔8 …)
- [x] Araç tipleri (otomobil, motosiklet, hafif ticari, kamyon, otobüs)
- [x] Tarife ve ücret hesaplama (ücretsiz süre, ilk saat, ek saat, günlük tavan)

## M2 — Veritabanı ve servis katmanı
- [ ] SQLAlchemy 2 modelleri: araç kaydı, park oturumu, tarife, olay günlüğü, kullanıcı
- [ ] Giriş/çıkış iş kuralları: tekrar okuma koruması, abone, kara liste, doluluk
- [ ] İstatistikler (içerideki araç, günlük giriş/çıkış, gelir, tip dağılımı)

## M3 — Tanıma motoru
- [ ] Araç tespiti + sınıflandırma (YOLOX ONNX; opsiyonel Ultralytics YOLO)
- [ ] Plaka tespiti + OCR (fast-alpr, ONNX)
- [ ] Plakayı araca eşleme, çoklu kare oylama ve tekrar engelleme
- [ ] `plakatanima recognize` ile resim/video üzerinde deneme

## M4 — Kamera ve demo altyapısı
- [ ] Webcam / RTSP / video dosyası kaynakları, otomatik yeniden bağlanma
- [ ] Kamera başına arka plan işleme döngüsü
- [ ] Kamera ve model olmadan denemek için demo (simülasyon) modu

## M5 — Masaüstü arayüz (PySide6)
- [ ] Koyu/açık tema, kenar menülü ana pencere
- [ ] Gösterge paneli: canlı kameralar, son geçişler, doluluk kartları
- [ ] Araçlar (abone / kara liste), park kayıtları, tarifeler, ayarlar sayfaları
- [ ] Manuel giriş/çıkış, ödeme alma, kara liste alarmı

## M6 — Raporlama ve yönetim
- [ ] Grafikli raporlar (saatlik yoğunluk, araç tipi dağılımı, gelir)
- [ ] CSV / Excel dışa aktarma
- [ ] Kullanıcı girişi ve roller (yönetici / operatör)
- [ ] Veritabanı yedekleme, eski görüntüleri temizleme

## Sonraki adımlar (planlanan)
- [ ] Bariyer/röle kontrolü (HTTP, seri port, GPIO)
- [ ] REST API (FastAPI) ve web paneli
- [ ] Türk plakaları ile ince ayarlı (fine-tuned) OCR / araç sınıflandırma modeli
- [ ] Birden fazla otopark / şube desteği, PostgreSQL ile merkezi veritabanı
- [ ] Docker imajı ve Windows kurulum paketi
