"""Bakım: veritabanı yedekleme ve eski yedeklerin temizlenmesi."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from plakatanima.db.database import Database

log = logging.getLogger(__name__)

BACKUP_PREFIX = "plakatanima-"
DEFAULT_KEEP = 14


@dataclass(frozen=True, slots=True)
class BackupInfo:
    path: Path
    created: datetime
    size: int


class BackupError(RuntimeError):
    pass


def backup_database(db: Database, backups_dir: Path, *, keep: int = DEFAULT_KEEP) -> Path:
    """SQLite veritabanının tutarlı bir kopyasını alır (uygulama çalışırken de güvenli)."""
    url = db.engine.url
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise BackupError(
            "Otomatik yedekleme yalnızca dosya tabanlı SQLite için desteklenir; "
            "PostgreSQL için pg_dump kullanın."
        )
    backups_dir.mkdir(parents=True, exist_ok=True)
    target = backups_dir / f"{BACKUP_PREFIX}{datetime.now():%Y%m%d-%H%M%S}.db"
    source = sqlite3.connect(url.database)
    try:
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()
    log.info("Veritabanı yedeklendi: %s", target)
    prune_backups(backups_dir, keep)
    return target


def list_backups(backups_dir: Path) -> list[BackupInfo]:
    if not backups_dir.is_dir():
        return []
    backups = []
    for path in backups_dir.glob(f"{BACKUP_PREFIX}*.db"):
        stat = path.stat()
        backups.append(BackupInfo(path, datetime.fromtimestamp(stat.st_mtime), stat.st_size))
    return sorted(backups, key=lambda b: b.created, reverse=True)


def prune_backups(backups_dir: Path, keep: int) -> int:
    removed = 0
    for info in list_backups(backups_dir)[keep:]:
        info.path.unlink(missing_ok=True)
        removed += 1
    return removed


def backup_if_due(
    db: Database, backups_dir: Path, *, every: timedelta = timedelta(days=1)
) -> Path | None:
    """Son yedek ``every`` süresinden eskiyse yeni yedek alır (açılışta çağrılır)."""
    backups = list_backups(backups_dir)
    if backups and datetime.now() - backups[0].created < every:
        return None
    try:
        return backup_database(db, backups_dir)
    except (BackupError, sqlite3.Error, OSError) as exc:
        log.warning("Otomatik yedek alınamadı: %s", exc)
        return None
