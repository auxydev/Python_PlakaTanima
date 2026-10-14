from __future__ import annotations

import os

import pytest

# Arayüz testleri ekran olmadan (CI) çalışabilsin.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """Testler kullanıcının gerçek ayar/veri dizinine dokunmasın."""
    monkeypatch.setenv("PLAKATANIMA_HOME", str(tmp_path / "home"))
