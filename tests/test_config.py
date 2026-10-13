from __future__ import annotations

import pytest

from plakatanima.cli import main
from plakatanima.config import AppConfig, CameraConfig, CameraRole, ConfigError, load_config
from plakatanima.paths import default_paths


def test_defaults_roundtrip_through_toml(tmp_path):
    path = tmp_path / "config.toml"
    config = load_config(path)
    assert path.exists()
    assert config.cameras[0].role is CameraRole.ENTRY

    config.parking.capacity = 42
    config.cameras.append(CameraConfig(name="Çıkış", source="rtsp://cam/2", role=CameraRole.EXIT))
    config.cameras[0].roi = (0.1, 0.2, 0.9, 1.0)
    config.save(path)

    loaded = load_config(path)
    assert loaded == config
    assert loaded.cameras[1].role is CameraRole.EXIT
    # None alanlar TOML'a yazılmaz, varsayılan olarak geri gelir.
    assert loaded.database.url is None


def test_invalid_values_raise_config_error():
    with pytest.raises(ConfigError):
        AppConfig.from_toml("[parking]\ncapacity = -5\n")
    with pytest.raises(ConfigError):
        AppConfig.from_toml("bu = geçerli toml değil = \n")
    with pytest.raises(ConfigError):
        AppConfig.from_toml("[[cameras]]\nroi = [0.5, 0.5, 0.2, 0.9]\n")


def test_unknown_keys_are_ignored():
    config = AppConfig.from_toml("eski_ayar = 1\n[parking]\ncapacity = 7\nbilinmeyen = true\n")
    assert config.parking.capacity == 7


def test_portable_home_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAKATANIMA_HOME", str(tmp_path / "portable"))
    paths = default_paths().ensure()
    assert paths.config_file == (tmp_path / "portable" / "config.toml").resolve()
    assert paths.database_file.parent.exists()


def test_cli_config_show(capsys):
    assert main(["config", "--show"]) == 0
    out = capsys.readouterr().out
    assert "[parking]" in out
    assert "capacity = 100" in out


def test_cli_init_db_and_status(capsys):
    assert main(["init-db"]) == 0
    assert "Veritabanı hazır" in capsys.readouterr().out
    assert main(["status"]) == 0
    assert "İçerideki araç : 0 / 100" in capsys.readouterr().out


def test_cli_user_backup_export(capsys, monkeypatch, tmp_path):
    passwords = iter(["gizli1", "gizli1", "yeni22", "yeni22"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(passwords))
    assert main(["user", "add", "kasa", "--role", "operator", "--name", "Kasa 1"]) == 0
    assert main(["user", "passwd", "kasa"]) == 0
    assert main(["user", "list"]) == 0
    out = capsys.readouterr().out
    assert "kasa" in out and "admin" in out
    assert main(["user", "delete", "yok"]) == 1

    assert main(["backup"]) == 0
    assert "Yedek alındı" in capsys.readouterr().out

    target = tmp_path / "rapor.xlsx"
    assert main(["export", str(target), "--start", "01.10.2026", "--end", "2026-10-13"]) == 0
    assert target.is_file()
    assert main(["export", str(tmp_path / "rapor.txt")]) == 2
