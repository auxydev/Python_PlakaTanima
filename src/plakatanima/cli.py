"""Komut satırı arayüzü.

Örnekler::

    plakatanima                          # masaüstü arayüzünü açar
    plakatanima gui --demo               # kamera olmadan demo
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

    gui = sub.add_parser("gui", help="masaüstü arayüzünü aç (varsayılan)")
    gui.add_argument("--demo", action="store_true", help="kamera/model olmadan simülasyon")

    run = sub.add_parser("run", help="kameraları arayüz olmadan çalıştır (sunucu modu)")
    run.add_argument("--demo", action="store_true", help="kamera/model olmadan simülasyon")
    run.add_argument("--duration", type=float, help="belirtilen saniye sonra dur")

    user = sub.add_parser("user", help="kullanıcı yönetimi")
    user_sub = user.add_subparsers(dest="user_command", required=True)
    user_sub.add_parser("list", help="kullanıcıları listele")
    add = user_sub.add_parser("add", help="kullanıcı ekle")
    add.add_argument("username")
    add.add_argument("--role", choices=["yonetici", "operator"], default="operator")
    add.add_argument("--name", default="", help="ad soyad")
    passwd = user_sub.add_parser("passwd", help="parola sıfırla (unutulan parola için)")
    passwd.add_argument("username")
    delete = user_sub.add_parser("delete", help="kullanıcı sil")
    delete.add_argument("username")

    sub.add_parser("backup", help="veritabanını yedekle")

    export = sub.add_parser("export", help="geçiş kayıtlarını Excel/CSV olarak dışa aktar")
    export.add_argument("output", type=Path, help="çıktı dosyası (.xlsx veya .csv)")
    export.add_argument("--start", type=_parse_date, help="başlangıç günü (GG.AA.YYYY)")
    export.add_argument("--end", type=_parse_date, help="bitiş günü (GG.AA.YYYY)")

    rec = sub.add_parser("recognize", help="resim/video üzerinde plaka ve araç tanıma")
    rec.add_argument("input", type=Path, help="resim veya video dosyası")
    rec.add_argument("-o", "--output", type=Path, help="işaretlenmiş resim/video çıktısı")
    rec.add_argument("--roi", type=_parse_roi, help="ilgi alanı: x1,y1,x2,y2 (0-1 arası)")
    rec.add_argument(
        "--foreign", action="store_true", help="Türk formatına uymayan plakaları da kabul et"
    )
    return parser


def _parse_date(value: str):
    from datetime import datetime

    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise argparse.ArgumentTypeError("Tarih biçimi: GG.AA.YYYY veya YYYY-AA-GG")


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


def _read_password(prompt: str = "Parola") -> str:
    import getpass

    first = getpass.getpass(f"{prompt}: ")
    if first != getpass.getpass(f"{prompt} (tekrar): "):
        raise ValueError("Parolalar eşleşmiyor")
    return first


def _cmd_user(args: argparse.Namespace, paths: AppPaths) -> int:
    from plakatanima.context import AppContext
    from plakatanima.core.formatting import format_datetime
    from plakatanima.db.models import UserRole
    from plakatanima.services.auth import AuthError

    ctx = AppContext.create(args.config, paths)
    users = ctx.users
    try:
        if args.user_command == "list":
            for user in users.list():
                state = "etkin" if user.is_active else "pasif"
                print(
                    f"{user.username:<16} {user.role.label:<10} {state:<6} "
                    f"son giriş: {format_datetime(user.last_login)}  {user.full_name}"
                )
            return 0
        if args.user_command == "add":
            users.create(
                args.username, _read_password(), role=UserRole(args.role), full_name=args.name
            )
            print(f"Kullanıcı eklendi: {args.username}")
            return 0
        user = users.get(args.username)
        if user is None:
            print(f"Kullanıcı bulunamadı: {args.username}", file=sys.stderr)
            return 1
        if args.user_command == "passwd":
            users.set_password(user.id, _read_password("Yeni parola"))
            users.update(user.id, is_active=True)
            print(f"Parola güncellendi: {user.username}")
        elif args.user_command == "delete":
            users.delete(user.id)
            print(f"Kullanıcı silindi: {user.username}")
        return 0
    except (AuthError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    finally:
        ctx.close()


def _cmd_backup(args: argparse.Namespace, paths: AppPaths) -> int:
    from plakatanima.context import AppContext
    from plakatanima.services.maintenance import BackupError, backup_database

    ctx = AppContext.create(args.config, paths)
    try:
        print(f"Yedek alındı: {backup_database(ctx.db, ctx.paths.backups_dir)}")
        return 0
    except BackupError as exc:
        print(exc, file=sys.stderr)
        return 1
    finally:
        ctx.close()


def _cmd_export(args: argparse.Namespace, paths: AppPaths) -> int:
    from datetime import date, timedelta

    from plakatanima.context import AppContext
    from plakatanima.services.reports import (
        export_sessions_csv,
        export_sessions_xlsx,
        sessions_for_export,
    )

    end = args.end or date.today()
    start = args.start or end - timedelta(days=29)
    suffix = args.output.suffix.lower()
    if suffix not in (".xlsx", ".csv"):
        print("Çıktı dosyası .xlsx veya .csv olmalı", file=sys.stderr)
        return 2
    ctx = AppContext.create(args.config, paths)
    try:
        sessions = sessions_for_export(ctx.db, start, end)
        if suffix == ".xlsx":
            summary = ctx.reports.summary(start, end)
            export_sessions_xlsx(
                sessions, args.output, summary=summary, currency=ctx.config.parking.currency
            )
        else:
            export_sessions_csv(sessions, args.output)
    finally:
        ctx.close()
    print(f"{len(sessions)} kayıt ({start:%d.%m.%Y} – {end:%d.%m.%Y}) → {args.output}")
    return 0


def _cmd_gui(args: argparse.Namespace, paths: AppPaths) -> int:
    from plakatanima.gui.app import run_gui

    return run_gui(args.config, paths, demo=getattr(args, "demo", False))


def _cmd_run(args: argparse.Namespace, paths: AppPaths) -> int:
    import threading

    from plakatanima.camera.manager import CameraManager
    from plakatanima.camera.runner import CameraCallbacks
    from plakatanima.context import AppContext

    ctx = AppContext.create(args.config, paths, demo=args.demo)
    if not any(c.enabled for c in ctx.config.cameras):
        print("Etkin kamera yok. Ayar dosyasına kamera ekleyin:", ctx.config_path, file=sys.stderr)
        return 1
    lock = threading.Lock()

    def on_plate(_index, observation, _confirmed):
        with lock:  # kameralar aynı anda okursa kayıtlar sırayla işlensin
            result = ctx.parking.process(observation)
        flag = " [!]" if result.is_alert else ""
        print(f"{result.timestamp:%H:%M:%S} [{result.camera_name}] {result.message}{flag}")

    def on_status(index, status, message):
        name = ctx.config.cameras[index].name
        print(f"[{name}] {status.label}{': ' + message if message else ''}")

    manager = CameraManager(
        ctx.config,
        ctx.paths,
        CameraCallbacks(on_plate=on_plate, on_status=on_status),
        inside_vehicles=ctx.inside_vehicles,
        registered_vehicles=ctx.registered_vehicles,
    )
    stop = threading.Event()
    manager.start()
    print("Çalışıyor. Durdurmak için Ctrl+C.")
    try:
        stop.wait(args.duration)
    except KeyboardInterrupt:
        pass
    finally:
        manager.stop()
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
        print(
            f"{len(analysis.vehicles)} araç, {len(analysis.plates)} plaka "
            f"({analysis.elapsed_ms:.0f} ms)"
        )
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
        if args.command == "run":
            return _cmd_run(args, paths)
        if args.command == "user":
            return _cmd_user(args, paths)
        if args.command == "backup":
            return _cmd_backup(args, paths)
        if args.command == "export":
            return _cmd_export(args, paths)
        return _cmd_gui(args, paths)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
