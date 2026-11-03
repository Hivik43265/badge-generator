"""Тестовые хелперы (не для продакшн-кода)."""
from __future__ import annotations
import sqlite3
from pathlib import Path
from . import db


def create_legacy_db(path, version: int = 1) -> Path:
    """Создать файл БД со схемой ровно версии `version` (без последующих миграций).

    Нужен для проверки миграций vN→LATEST без прямого SQL в вызывающем коде.
    """
    if not 0 <= version <= len(db.MIGRATIONS):
        raise ValueError(f"version must be 0..{len(db.MIGRATIONS)}")
    path = Path(path)
    if path.exists():
        raise FileExistsError(path)
    con = sqlite3.connect(path)
    try:
        for i, step in enumerate(db.MIGRATIONS[:version]):
            if isinstance(step, str):
                con.executescript("BEGIN;\n" + step + f"\nPRAGMA user_version={i+1};\nCOMMIT;")
            else:
                con.execute("BEGIN"); step(con)
                con.execute(f"PRAGMA user_version={i+1}"); con.execute("COMMIT")
    finally:
        con.close()
    return path
