"""Komut satırı arayüzü.

Örnekler::

    plakatanima                          # masaüstü arayüzünü açar
    plakatanima config --show            # aktif ayarları yazdırır
    plakatanima recognize araba.jpg -o sonuc.jpg
    plakatanima recognize giris.mp4      # videodaki plakaları listeler
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from plakatanima import APP_DISPLAY_NAME, __version__
from plakatanima.config import AppConfig, ConfigError, load_config
from plakatanima.logging_setup import setup_logging
from plakatanima.paths import AppPaths, default_paths


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="plakatanima", description=APP_DISPLAY_NAME)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--config", type=Path, help="ayar dosyası (varsayılan: kullanıcı dizini)")
    parser.add_argument("-v", "--verbose", action="store_true", help="ayrıntılı log")
    sub = parser.add_subparsers(dest="command")

    cfg = sub.add_parser("config", help="ayar dosyasını göster")
    cfg.add_argument("--show", action="store_true", help="aktif ayarları yazdır")

    sub.add_parser("init-db", help="veritabanını oluştur / eksik tabloları ekle")
    sub.add_parser("status", help="otopark doluluk ve günlük özet")

    rec = sub.add_parser("recognize", help="resim/video üzerinde plaka ve araç tanıma")
    rec.add_argument("input", type=Path, help="resim veya video dosyası")
    rec.add_argument("-o", "--output", type=Path, help="işaretlenmiş resim/video çıktısı")
    rec.add_argument("--roi", type=_parse_roi, help="ilgi alanı: x1,y1,x2,y2 (0-1 arası)")
    rec.add_argument(
        "--foreign", action="store_true", help="Türk formatına uymayan plakaları da kabul et"
    )
    return parser


def _parse_roi(value: str) -> tuple[float, float, float, float]:
    try:
        x1, y1, x2, y2 = (float(v) for v in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("ROI biçimi: x1,y1,x2,y2 (ör. 0,0.3,1,1)") from exc
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        raise argparse.ArgumentTypeError("ROI değerleri 0-1 arasında ve x1<x2, y1<y2 olmalı")
    return x1, y1, x2, y2


def _load(args: argparse.Namespace, paths: AppPaths) -> AppConfig:
    return load_config(args.config or paths.config_file)


def _cmd_config(args: argparse.Namespace, paths: AppPaths) -> int:
    config_path = args.config or paths.config_file
    config = _load(args, paths)
    print(f"Ayar dosyası : {config_path}")
    print(f"Veri dizini  : {paths.data_dir}")
    if args.show:
        print()
        print(config.to_toml())
    return 0


def _cmd_init_db(args: argparse.Namespace, paths: AppPaths) -> int:
    from plakatanima.context import AppContext

    ctx = AppContext.create(args.config, paths)
    print(f"Veritabanı hazır: {ctx.db.engine.url.render_as_string(hide_password=True)}")
    ctx.close()
    return 0


def _cmd_status(args: argparse.Namespace, paths: AppPaths) -> int:
    from plakatanima.context import AppContext
    from plakatanima.core.formatting import format_money

    ctx = AppContext.create(args.config, paths)
    stats = ctx.parking.dashboard_stats()
    currency = ctx.config.parking.currency
    print(f"{ctx.config.parking.lot_name}")
    print(f"  İçerideki araç : {stats.inside} / {stats.capacity}")
    print(f"  Bugün giriş    : {stats.entries_today}")
    print(f"  Bugün çıkış    : {stats.exits_today}")
    print(f"  Bugün tahsilat : {format_money(stats.revenue_today, currency)}")
    print(f"  Ödeme bekleyen : {stats.unpaid_count}")
    for vehicle_type, count in sorted(stats.inside_by_type.items()):
        print(f"    {vehicle_type.label:<18}: {count}")
    ctx.close()
    return 0


def _cmd_recognize(args: argparse.Namespace, paths: AppPaths) -> int:
    from plakatanima.core.plate import format_plate
    from plakatanima.recognition import offline
    from plakatanima.recognition.factory import build_pipeline, build_voter
    from plakatanima.recognition.model_store import ModelError
    from plakatanima.recognition.pipeline import annotate

    config = _load(args, paths)
    if args.foreign:
        config.recognition.turkish_plates_only = False
    if not args.input.exists():
        print(f"Dosya bulunamadı: {args.input}", file=sys.stderr)
        return 1
    try:
        pipeline = build_pipeline(config.recognition, paths.models_dir)
    except ModelError as exc:
        print(exc, file=sys.stderr)
        return 1

    if offline.is_image(args.input):
        frame = offline.read_image(args.input)
        analysis = pipeline.analyze(frame, args.roi)
        print(f"{len(analysis.vehicles)} araç, {len(analysis.plates)} plaka "
              f"({analysis.elapsed_ms:.0f} ms)")  # fmt: skip
        for vehicle in analysis.vehicles:
            print(f"  araç  : {vehicle.vehicle_type.label:<18} %{vehicle.confidence * 100:.0f}")
        for plate in analysis.plates:
            print(
                f"  plaka : {format_plate(plate.text):<12} %{plate.confidence * 100:.0f}  "
                f"{plate.vehicle_type.label}  (OCR: {plate.raw_text})"
            )
        for raw in analysis.rejected:
            print(f"  elendi: {raw.text} %{raw.confidence * 100:.0f} {raw.region or ''}")
        if args.output:
            offline.write_image(args.output, annotate(frame, analysis, args.roi))
            print(f"Kaydedildi: {args.output}")
        return 0

    writer = None

    def on_frame(_ts, frame, analysis):
        nonlocal writer
        if args.output is None:
            return
        if writer is None:
            import cv2

            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            size = (frame.shape[1], frame.shape[0])
            writer = cv2.VideoWriter(str(args.output), fourcc, fps, size)
        writer.write(annotate(frame, analysis, args.roi))

    fps = config.cameras[0].process_fps if config.cameras else 4.0
    voter = build_voter(config.recognition)
    count = 0
    try:
        for timestamp, confirmed in offline.recognize_video(
            pipeline, voter, args.input, process_fps=fps, roi=args.roi, on_frame=on_frame
        ):
            count += 1
            minutes, seconds = divmod(timestamp, 60)
            print(
                f"[{int(minutes):02d}:{seconds:05.2f}] {format_plate(confirmed.plate):<12} "
                f"%{confirmed.confidence * 100:.0f}  {confirmed.vehicle_type.label}  "
                f"({confirmed.hits} okuma)"
            )
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    finally:
        if writer is not None:
            writer.release()
    print(f"Toplam {count} plaka onaylandı.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    paths = default_paths().ensure()
    setup_logging(paths.logs_dir, verbose=args.verbose)

    try:
        if args.command == "config":
            return _cmd_config(args, paths)
        if args.command == "init-db":
            return _cmd_init_db(args, paths)
        if args.command == "status":
            return _cmd_status(args, paths)
        if args.command == "recognize":
            return _cmd_recognize(args, paths)
        parser.print_help()
        return 0
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
