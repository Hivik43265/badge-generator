"""Этап 11: пути БД/schema.sql в frozen-режиме (PyInstaller)."""
import sys
from pathlib import Path
from badge_backend import db

def test_not_frozen_unchanged(tmp_path):
    assert db.default_db_path(tmp_path) == tmp_path / "project.db"
    assert db.default_db_path() == Path.cwd() / "project.db"
    assert db.SCHEMA_PATH.exists()

def test_frozen_meipass_goes_to_projects_dir(tmp_path, monkeypatch):
    mei = tmp_path / "_MEI123"; mei.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(mei), raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    monkeypatch.setenv("BG_APP_ROOT", str(tmp_path / "app"))
    exp = tmp_path / "app" / "projects" / "project.db"   # замечание №1: рядом с exe, не %APPDATA%
    assert db.default_db_path(mei) == exp
    assert db.default_db_path() == exp
    assert exp.parent.is_dir()
    other = tmp_path / "proj"
    assert db.default_db_path(other) == other / "project.db"   # явный каталог вне _MEIPASS — как есть
