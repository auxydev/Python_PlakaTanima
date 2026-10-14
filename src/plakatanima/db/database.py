"""Veritabanı bağlantısı, oturum yönetimi ve ilk kurulum verileri."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from plakatanima.core.pricing import DEFAULT_TARIFFS
from plakatanima.db.models import Base, Tariff

log = logging.getLogger(__name__)


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _is_memory(url: str) -> bool:
    return url in ("sqlite://", "sqlite:///:memory:")


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        kwargs: dict = {}
        if _is_sqlite(url):
            # Kamera iş parçacıkları da yazabildiği için bağlantı thread'ler arasında paylaşılır.
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
            if _is_memory(url):
                kwargs["poolclass"] = StaticPool
        self.engine: Engine = create_engine(url, **kwargs)
        if _is_sqlite(url):
            event.listen(self.engine, "connect", _sqlite_pragmas)
        self._session_factory = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """İşlem (transaction) bloğu: hata olmazsa commit, olursa rollback."""
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def create_schema(self) -> None:
        """Eksik tabloları oluşturur ve varsayılan tarifeleri ekler."""
        Base.metadata.create_all(self.engine)
        with self.session() as s:
            existing = set(s.scalars(select(Tariff.vehicle_type)))
            for vehicle_type, rule in DEFAULT_TARIFFS.items():
                if vehicle_type in existing:
                    continue
                s.add(
                    Tariff(
                        vehicle_type=vehicle_type,
                        free_minutes=rule.free_minutes,
                        first_hour_fee=rule.first_hour_fee,
                        additional_hour_fee=rule.additional_hour_fee,
                        daily_max_fee=rule.daily_max_fee,
                    )
                )
        log.info("Veritabanı hazır: %s", self.engine.url.render_as_string(hide_password=True))

    def dispose(self) -> None:
        self.engine.dispose()


def _sqlite_pragmas(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()
