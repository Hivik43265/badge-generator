"""SQLite слой: одна схема (schema.sql) + миграции через PRAGMA user_version.

Версия 1 = schema.sql. Новые версии добавляются в MIGRATIONS как ALTER-скрипты
и применяются по порядку и к новым, и к существующим БД.
"""
import sqlite3
from pathlib import Path
DEFAULT_DB_PATH = "project.db"   # имя файла БД проекта; относительный путь — от каталога проекта (по умолчанию cwd)

def _frozen_data_dir() -> Path:
    """Каталог данных для собранного exe (PyInstaller): %APPDATA%\\BadgeGenerator (иначе ~/.BadgeGenerator)."""
    import os
    base = os.environ.get("APPDATA")
    d = Path(base) / "BadgeGenerator" if base else Path.home() / ".BadgeGenerator"
    d.mkdir(parents=True, exist_ok=True)
    return d

def default_db_path(project_dir=None) -> Path:
    """Путь к БД по умолчанию: <project_dir или cwd>/project.db.
    В frozen-режиме (PyInstaller) каталог внутри _MEIPASS (или не задан) заменяется на %APPDATA%\\BadgeGenerator."""
    import sys
    if getattr(sys, "frozen", False):
        mei = getattr(sys, "_MEIPASS", None)
        pd = Path(project_dir).resolve() if project_dir else None
        if pd is None or (mei and (pd == Path(mei).resolve() or Path(mei).resolve() in pd.parents)):
            return _frozen_data_dir() / DEFAULT_DB_PATH
    return Path(project_dir or Path.cwd()) / DEFAULT_DB_PATH

def _schema_path() -> Path:
    import sys
    p = Path(__file__).with_name("schema.sql")
    mei = getattr(sys, "_MEIPASS", None)
    if not p.exists() and mei:
        p = Path(mei) / "badge_backend" / "schema.sql"
    return p

SCHEMA_PATH = _schema_path()
SCHEMA = SCHEMA_PATH.read_text(encoding="utf-8")
def _cols(con, table):
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}

def _v2_printed_at(con):
    """v2: persons.printed_at TEXT NULL — ISO 8601, локальное время со смещением (см. now_iso)."""
    if "printed_at" not in _cols(con, "persons"):
        con.execute("ALTER TABLE persons ADD COLUMN printed_at TEXT NULL")

_TE_V3 = """CREATE TABLE template_elements (
    id           INTEGER PRIMARY KEY,
    type         TEXT NOT NULL CHECK (type IN ('text','field','photo','image','rect','qr','barcode','line')),
    x INTEGER NOT NULL, y INTEGER NOT NULL,
    w INTEGER NOT NULL, h INTEGER NOT NULL,   -- px холста 1011x638; для line — вектор (dx, dy), может быть <=0
    field_name   TEXT,
    static_value TEXT,
    style_json   TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(style_json)),
    side         TEXT NOT NULL DEFAULT 'front' CHECK (side IN ('front','back')),
    z_order      INTEGER NOT NULL DEFAULT 0,
    CHECK (type <> 'field' OR field_name IS NOT NULL),
    CHECK ((type <> 'line' AND w > 0 AND h > 0) OR (type = 'line' AND NOT (w = 0 AND h = 0))))"""

def _v3_line(con):
    """v3: тип 'line' — пересборка template_elements (CHECK нельзя изменить ALTER'ом).
    Данные и id копируются, индекс пересоздаётся. Идемпотентно: если 'line' уже в CHECK — ничего не делает."""
    sql = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='template_elements'").fetchone()[0]
    if "'line'" in sql: return
    cols = "id,type,x,y,w,h,field_name,static_value,style_json,side,z_order"
    con.execute("ALTER TABLE template_elements RENAME TO _te_old")
    con.execute(_TE_V3)
    con.execute(f"INSERT INTO template_elements({cols}) SELECT {cols} FROM _te_old")
    con.execute("DROP TABLE _te_old")
    con.execute("CREATE INDEX IF NOT EXISTS idx_te_side_z ON template_elements(side, z_order)")

_TE_V4 = _TE_V3.replace("'barcode','line')", "'barcode','line','ellipse')")

def _v4_ellipse_defaults(con):
    """v4: тип 'ellipse' в CHECK template_elements (пересборка, данные и id сохраняются)
    + person_fields.default_value TEXT NULL. Идемпотентно."""
    sql = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='template_elements'").fetchone()[0]
    if "'ellipse'" not in sql:
        cols = "id,type,x,y,w,h,field_name,static_value,style_json,side,z_order"
        con.execute("ALTER TABLE template_elements RENAME TO _te_old")
        con.execute(_TE_V4)
        con.execute(f"INSERT INTO template_elements({cols}) SELECT {cols} FROM _te_old")
        con.execute("DROP TABLE _te_old")
        con.execute("CREATE INDEX IF NOT EXISTS idx_te_side_z ON template_elements(side, z_order)")
    if "default_value" not in _cols(con, "person_fields"):
        con.execute("ALTER TABLE person_fields ADD COLUMN default_value TEXT NULL")

def _v5_field_types(con):
    """v5 (D24): person_fields.data_type TEXT NOT NULL DEFAULT 'text' CHECK (text|number|date|image|bool).
    Существующие поля получают 'text'. Автоматических/демо полей схема не создаёт (и никогда не создавала).
    Идемпотентно."""
    if "data_type" not in _cols(con, "person_fields"):
        con.execute("ALTER TABLE person_fields ADD COLUMN data_type TEXT NOT NULL DEFAULT 'text' "
                    "CHECK (data_type IN ('text','number','date','image','bool'))")

MIGRATIONS = [SCHEMA, _v2_printed_at, _v3_line, _v4_ellipse_defaults, _v5_field_types]   # индекс + 1 = user_version; str — SQL-скрипт, callable — шаг на Python
LATEST = len(MIGRATIONS)

def now_iso() -> str:
    """Текущее локальное время, ISO 8601 со смещением: '2026-11-03T16:40:12+03:00'."""
    from datetime import datetime
    return datetime.now().astimezone().isoformat(timespec="seconds")

def migrate(con) -> int:
    """Применить недостающие миграции (идемпотентно, каждая — в своей транзакции). → user_version."""
    v = con.execute("PRAGMA user_version").fetchone()[0]
    for i in range(v, LATEST):
        step = MIGRATIONS[i]
        if isinstance(step, str):
            con.executescript("BEGIN;\n" + step + f"\nPRAGMA user_version={i+1};\nCOMMIT;")
        else:
            con.execute("BEGIN")
            try:
                step(con); con.execute(f"PRAGMA user_version={i+1}"); con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK"); raise
    return con.execute("PRAGMA user_version").fetchone()[0]

def get_schema_version(con) -> int:
    """Текущая версия схемы БД (PRAGMA user_version); после migrate() == LATEST."""
    return int(con.execute("PRAGMA user_version").fetchone()[0])

def connect(path=":memory:") -> sqlite3.Connection:
    """Открыть БД (Row factory, foreign_keys=ON) и довести схему до LATEST."""
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    migrate(con)
    return con
