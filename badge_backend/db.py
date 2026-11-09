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

_V6_SETTINGS = """CREATE TABLE IF NOT EXISTS project_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);"""
# v6 (этап 14): настройки проекта key → value (JSON-строка); первая — photo_edit_defaults.

# ---------- v7 (этап 15) ----------
# Локальное время со смещением в SQL (как now_iso): 'YYYY-MM-DDTHH:MM:SS+HH:MM'. Используется в триггерах.
_OFS = "CAST(round((julianday('now','localtime') - julianday('now')) * 86400) AS INTEGER)"
LOCAL_NOW_SQL = (f"(strftime('%Y-%m-%dT%H:%M:%S','now','localtime') || CASE WHEN {_OFS} < 0 THEN '-' ELSE '+' END"
                 f" || printf('%02d:%02d', abs({_OFS}) / 3600, (abs({_OFS}) % 3600) / 60))")

_TE_V7 = """CREATE TABLE template_elements (
    id           INTEGER PRIMARY KEY,
    type         TEXT NOT NULL CHECK (type IN ('text','field','photo','image','rect','qr','barcode','line','ellipse')),
    x INTEGER NOT NULL, y INTEGER NOT NULL,
    w INTEGER NOT NULL, h INTEGER NOT NULL,
    field_name   TEXT,                 -- NULL у 'field' = объект отвязан (этап 15), рисуется static_value
    static_value TEXT,
    style_json   TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(style_json)),
    side         TEXT NOT NULL DEFAULT 'front' CHECK (side IN ('front','back')),
    z_order      INTEGER NOT NULL DEFAULT 0,
    template_id  INTEGER REFERENCES templates(id) ON DELETE CASCADE,
    CHECK ((type <> 'line' AND w > 0 AND h > 0) OR (type = 'line' AND NOT (w = 0 AND h = 0))))"""

PHOTO_FIELD = "Фото"
ACTIVE_KEY = "active_template_id"

def _utc_to_local(v):
    """'YYYY-MM-DD HH:MM:SS' (UTC из datetime('now')) → ISO с локальным смещением; иное — как есть."""
    from datetime import datetime, timezone
    if not isinstance(v, str) or "T" in v: return v
    try: d = datetime.strptime(v, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError: return v
    return d.astimezone().isoformat(timespec="seconds")


def _sync_photo_config_views(con):
    """persons.photo_config → person_photo_views[''].placement (единственный путь рендера).
    Колонка photo_config остаётся. Идемпотентно: можно вызывать на уже-v7 БД, где перенос не сделали."""
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "person_photo_views" not in tables or "photo_config" not in _cols(con, "persons"):
        return
    con.execute(f"""INSERT OR IGNORE INTO person_photo_views(person_id, field_name, params_json, updated_at)
        SELECT id, '', json_object('placement', COALESCE(photo_config, '0;0;1.0;0;0;0')), {LOCAL_NOW_SQL} FROM persons""")
    for trg, ev in (("persons_photo_config_ins", "AFTER INSERT ON persons"),
                    ("persons_photo_config_upd", "AFTER UPDATE OF photo_config ON persons WHEN NEW.photo_config IS NOT OLD.photo_config")):
        con.execute(f"DROP TRIGGER IF EXISTS {trg}")
        con.execute(f"""CREATE TRIGGER {trg} {ev} BEGIN
            INSERT INTO person_photo_views(person_id, field_name, params_json, updated_at)
            VALUES (NEW.id, '', json_object('placement', COALESCE(NEW.photo_config, '0;0;1.0;0;0;0')), {LOCAL_NOW_SQL})
            ON CONFLICT(person_id, field_name) DO UPDATE SET
                params_json = json_set(params_json, '$.placement', json_extract(excluded.params_json, '$.placement')),
                updated_at = excluded.updated_at; END""")


def _v7_templates(con):
    """v7 (этап 15): несколько шаблонов, вид фото записи, поле «Фото», локальное время. Идемпотентно по частям.
    1) templates (+style_json — шрифт/отступы шаблона); все элементы и фоны → шаблон «Основной» (активный);
    2) template_elements пересобирается: + template_id, снят CHECK «field ⇒ field_name» (отвязанный объект остаётся полем);
    3) template_backgrounds2 (template_id, side); старая template_backgrounds не удаляется (legacy, только чтение);
    4) person_photo_views (вид фото записи, исходник не меняется);
    5) есть фото (photo_path у записей или фото-объекты) и нет ни одного image-поля → создаётся «Фото», persons.photo_path копируется в него, несвязанные фото-объекты
       связываются с ним (файлы и photo_path не трогаются);
    7) persons.photo_config → person_photo_views[''] {'placement': ...} + триггеры синхронизации (колонка остаётся);
    6) время: триггеры пишут локальное время со смещением; старые created_at/updated_at (UTC) → локальные."""
    con.execute("""CREATE TABLE IF NOT EXISTS templates (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
        style_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(style_json)),
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    now = now_iso()
    r = con.execute("SELECT id FROM templates ORDER BY id LIMIT 1").fetchone()
    tid = r[0] if r else con.execute("INSERT INTO templates(name, created_at, updated_at) VALUES ('Основной', ?, ?)",
                                     (now, now)).lastrowid
    if "template_id" not in _cols(con, "template_elements"):
        cols = "id,type,x,y,w,h,field_name,static_value,style_json,side,z_order"
        con.execute("ALTER TABLE template_elements RENAME TO _te_old")
        con.execute(_TE_V7)
        con.execute(f"INSERT INTO template_elements({cols},template_id) SELECT {cols}, ? FROM _te_old", (tid,))
        con.execute("DROP TABLE _te_old")
    con.execute("CREATE INDEX IF NOT EXISTS idx_te_side_z ON template_elements(side, z_order)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_te_tpl ON template_elements(template_id, side, z_order)")
    con.execute("""CREATE TABLE IF NOT EXISTS template_backgrounds2 (
        template_id INTEGER NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
        side TEXT NOT NULL CHECK (side IN ('front','back')), image_path TEXT, color TEXT NOT NULL DEFAULT '#FFFFFF',
        PRIMARY KEY (template_id, side))""")
    con.execute("INSERT OR IGNORE INTO template_backgrounds2(template_id, side, image_path, color) "
                "SELECT ?, side, image_path, color FROM template_backgrounds", (tid,))
    con.execute("""CREATE TABLE IF NOT EXISTS person_photo_views (
        person_id INTEGER NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
        field_name TEXT NOT NULL DEFAULT '',
        params_json TEXT NOT NULL CHECK (json_valid(params_json)),
        updated_at TEXT NOT NULL, PRIMARY KEY (person_id, field_name))""")
    con.execute("INSERT OR IGNORE INTO project_settings(key, value) VALUES (?, ?)", (ACTIVE_KEY, str(tid)))
    # триггеры — до правок persons, чтобы старый persons_touch не переписал updated_at
    con.execute("DROP TRIGGER IF EXISTS persons_touch")
    con.execute(f"""CREATE TRIGGER persons_touch AFTER UPDATE ON persons WHEN NEW.updated_at = OLD.updated_at
        BEGIN UPDATE persons SET updated_at = {LOCAL_NOW_SQL} WHERE id = NEW.id; END""")
    con.execute("DROP TRIGGER IF EXISTS persons_created_local")
    con.execute(f"""CREATE TRIGGER persons_created_local AFTER INSERT ON persons
        WHEN instr(NEW.created_at, 'T') = 0 OR instr(NEW.updated_at, 'T') = 0
        BEGIN UPDATE persons SET
            created_at = CASE WHEN instr(NEW.created_at, 'T') = 0 THEN {LOCAL_NOW_SQL} ELSE NEW.created_at END,
            updated_at = CASE WHEN instr(NEW.updated_at, 'T') = 0 THEN {LOCAL_NOW_SQL} ELSE NEW.updated_at END
        WHERE id = NEW.id; END""")
    has_photo = con.execute("SELECT 1 FROM persons WHERE COALESCE(photo_path, '') <> '' UNION ALL "
                            "SELECT 1 FROM template_elements WHERE type='photo' LIMIT 1").fetchone() is not None
    # D24: пустой/новый проект полей не получает — «Фото» создаётся только там, где фото уже используется
    if has_photo and con.execute("SELECT 1 FROM person_fields WHERE data_type='image'").fetchone() is None:
        so = con.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM person_fields").fetchone()[0]
        con.execute("INSERT INTO person_fields(name, label, sort_order, data_type) VALUES (?, ?, ?, 'image') "
                    "ON CONFLICT(name) DO UPDATE SET data_type='image'", (PHOTO_FIELD, PHOTO_FIELD, so))
        con.execute("UPDATE persons SET fields_json = json_set(fields_json, ?, photo_path) "
                    "WHERE COALESCE(photo_path, '') <> '' AND COALESCE(json_extract(fields_json, ?), '') = ''",
                    ('$."Фото"', '$."Фото"'))
        con.execute("UPDATE template_elements SET field_name=? WHERE type='photo' AND COALESCE(field_name, '') = ''",
                    (PHOTO_FIELD,))
    _sync_photo_config_views(con)
    rows = con.execute("SELECT id, created_at, updated_at FROM persons").fetchall()
    for pid, c, u in rows:
        c2, u2 = _utc_to_local(c), _utc_to_local(u)
        if (c2, u2) != (c, u): con.execute("UPDATE persons SET created_at=?, updated_at=? WHERE id=?", (c2, u2, pid))

def active_template_id(con) -> int:
    """id активного шаблона (project_settings['active_template_id']); битое/нет → первый шаблон
    (настройка исправляется); шаблонов нет → создаётся «Основной»."""
    r = con.execute("SELECT value FROM project_settings WHERE key=?", (ACTIVE_KEY,)).fetchone()
    try: tid = int(r[0]) if r else None
    except (TypeError, ValueError): tid = None
    if tid is not None and con.execute("SELECT 1 FROM templates WHERE id=?", (tid,)).fetchone(): return tid
    r = con.execute("SELECT id FROM templates ORDER BY id LIMIT 1").fetchone()
    with con:
        if r: tid = r[0]
        else:
            n = now_iso()
            tid = con.execute("INSERT INTO templates(name, created_at, updated_at) VALUES ('Основной', ?, ?)", (n, n)).lastrowid
        con.execute("INSERT INTO project_settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (ACTIVE_KEY, str(tid)))
    return tid

MIGRATIONS = [SCHEMA, _v2_printed_at, _v3_line, _v4_ellipse_defaults, _v5_field_types, _V6_SETTINGS, _v7_templates]   # индекс + 1 = user_version; str — SQL-скрипт, callable — шаг на Python
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
    v = con.execute("PRAGMA user_version").fetchone()[0]
    if v >= 7:
        _sync_photo_config_views(con)
        con.commit()
    return v

def get_schema_version(con) -> int:
    """Текущая версия схемы БД (PRAGMA user_version); после migrate() == LATEST."""
    return int(con.execute("PRAGMA user_version").fetchone()[0])

_cleaned = False

def connect(path=":memory:") -> sqlite3.Connection:
    """Открыть БД (Row factory, foreign_keys=ON) и довести схему до LATEST.
    D48: при первом вызове в процессе (старт приложения — BackendAPI → connect) удаляются старые
    рабочие копии .db-импорта (sources._cleanup_stale_work_copies; ошибки только в лог)."""
    global _cleaned
    if not _cleaned:
        _cleaned = True
        try:
            from .services.sources import _cleanup_stale_work_copies
            _cleanup_stale_work_copies()
        except Exception:   # noqa: BLE001
            import logging; logging.getLogger(__name__).exception("очистка рабочих копий")
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    migrate(con)
    return con
