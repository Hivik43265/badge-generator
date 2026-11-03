"""Тестовые хелперы (не для продакшн-кода)."""
from __future__ import annotations
import sqlite3
from pathlib import Path
from . import db


def create_legacy_db(path, version: int = 1) -> Path:
    """Создать файл БД (version 0..6) со схемой ровно версии `version` (без последующих миграций).

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


def prepare_fields(con, src, mapping=None, labels=None, header: bool = True) -> list[str]:
    """ТОЛЬКО для тестов (D24: импорт не создаёт поля). Создать через upsert_field поля под колонки
    файла/листа `src` (путь или Sheet) по правилам map_headers — как делал импорт до D24. → имена полей."""
    from . import api
    from .services.headers import map_headers, column_labels
    if hasattr(src, "kind"):
        from .services.sources import read_rows
        heads, _ = read_rows(src, header=header, limit=1)
    else:
        from .services.importer import read_table
        heads, _ = read_table(src)
    keys = map_headers(heads, mapping)
    labs = column_labels(heads, keys, mapping, labels)
    have = {f["name"] for f in api.list_fields(con)}
    n = len(have)
    for k, lab in labs.items():
        if k not in have: api.upsert_field(con, k, lab, n); n += 1; have.add(k)
    return list(labs)


def import_with_fields(fn, con, src, mapping=None, *args, **kw):
    """ТОЛЬКО для тестов: prepare_fields + fn (api.import_file / api.import_rows).
    Проектный лист (.db) — через import_fields=True (поля переносит сам импорт)."""
    if getattr(src, "kind", None) == "project": kw.setdefault("import_fields", True)
    else: prepare_fields(con, src, mapping, kw.get("labels"), kw.get("header", True))
    return fn(con, src, mapping, *args, **kw)
