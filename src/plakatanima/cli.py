"""Komut satırı arayüzü.

Örnekler::

    plakatanima                 # masaüstü arayüzünü açar
    plakatanima config --show   # aktif ayarları yazdırır
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
    return parser


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


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    paths = default_paths().ensure()
    setup_logging(paths.logs_dir, verbose=args.verbose)

    try:
        if args.command == "config":
            return _cmd_config(args, paths)
        parser.print_help()
        return 0
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
