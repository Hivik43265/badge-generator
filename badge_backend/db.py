"""SQLite слой: одна схема (schema.sql) + миграции через PRAGMA user_version.

Версия 1 = schema.sql. Новые версии добавляются в MIGRATIONS как ALTER-скрипты
и применяются по порядку и к новым, и к существующим БД.
"""
import json, logging, re, sqlite3
from pathlib import Path
DEFAULT_DB_PATH = "project.db"   # имя файла БД проекта; относительный путь — от каталога проекта (по умолчанию cwd)
log = logging.getLogger(__name__)


class MigrationError(RuntimeError):
    """Миграция схемы не применилась; транзакция шага откачена, файл не изменён."""

def _legacy_frozen_db_path() -> Path | None:
    """Где exe держал БД до замечания №1: %APPDATA%\\BadgeGenerator\\project.db (нет APPDATA — ~/.BadgeGenerator).
    Ничего не создаёт."""
    from .app_paths import legacy_appdata_dir
    d = legacy_appdata_dir()
    return d / DEFAULT_DB_PATH if d else None


def _copy_legacy_db(old: Path, new: Path) -> bool:
    """Скопировать старую БД в новое место (backup API: согласованная копия, включая WAL). Старый файл не меняется
    и не удаляется. Новое место уже занято или ошибка → False (ошибка — в лог, без исключения)."""
    if new.exists() or not old.is_file(): return False
    tmp = new.with_name(new.name + ".copying")
    try:
        new.parent.mkdir(parents=True, exist_ok=True)
        tmp.unlink(missing_ok=True)
        src = sqlite3.connect(f"file:{old.resolve().as_posix()}?mode=ro", uri=True)
        try:
            dst = sqlite3.connect(str(tmp))
            try: src.backup(dst)
            finally: dst.close()
        finally:
            src.close()
        if new.exists():          # другой экземпляр успел раньше — его копию не трогаем
            tmp.unlink(missing_ok=True); return False
        tmp.replace(new)
        log.info("БД перенесена копированием: %s → %s (старый файл оставлен)", old, new)
        return True
    except Exception as e:  # noqa: BLE001 — старт программы не должен падать
        log.error("не удалось скопировать БД %s → %s: %s", old, new, e)
        try: tmp.unlink(missing_ok=True)
        except OSError: pass
        return False


def _frozen_default_db_path() -> Path:
    """Замечание №1 (доп., 11.11): БД собранного exe по умолчанию — app_paths.projects_dir()/project.db
    (<папка exe>/projects/project.db; нет прав — %LOCALAPPDATA%\\BadgeGenerator\\projects\\project.db).
    Миграция: в новом месте БД нет, а в старом %APPDATA%\\BadgeGenerator\\project.db есть → КОПИЯ (не перенос);
    старый файл никогда не удаляется и не меняется. Вместе с БД копируются photos/, template_bg/, .csd/.csp."""
    from .app_paths import projects_dir
    new = projects_dir() / DEFAULT_DB_PATH
    old = _legacy_frozen_db_path()
    if old is not None and not new.exists() and old.is_file():
        if _copy_legacy_db(old, new):
            _copy_legacy_companions(old, new)
    return new


_COMPANION_DIRS = ("photos", "template_bg")   # относительные пути фото и фонов в БД — от папки БД


def _copy_legacy_companions(old: Path, new: Path) -> None:
    """Вместе с БД копируются её спутники, иначе относительные пути сломаются: папки photos/ и template_bg/
    (только если в новом месте такой папки ещё нет) и <имя>.csd / <имя>.csp (если нет). Оригиналы не трогаются."""
    import shutil
    for d in _COMPANION_DIRS:
        src, dst = old.parent / d, new.parent / d
        try:
            if src.is_dir() and not dst.exists(): shutil.copytree(src, dst)
        except OSError as e:
            log.error("не удалось скопировать %s → %s: %s", src, dst, e)
    for ext in (".csd", ".csp"):
        src, dst = old.with_suffix(ext), new.with_suffix(ext)
        try:
            if src.is_file() and not dst.exists(): shutil.copy2(src, dst)
        except OSError as e:
            log.error("не удалось скопировать %s → %s: %s", src, dst, e)


def default_db_path(project_dir=None) -> Path:
    """Путь к БД по умолчанию: <project_dir или cwd>/project.db.
    В frozen-режиме (PyInstaller) каталог внутри _MEIPASS (или не задан) заменяется на
    _frozen_default_db_path() — <папка exe>/projects/project.db (замечание №1; раньше %APPDATA%\\BadgeGenerator)."""
    import sys
    if getattr(sys, "frozen", False):
        mei = getattr(sys, "_MEIPASS", None)
        pd = Path(project_dir).resolve() if project_dir else None
        if pd is None or (mei and (pd == Path(mei).resolve() or Path(mei).resolve() in pd.parents)):
            return _frozen_default_db_path()
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
    5) (снято замечанием №4, 11.11) раньше здесь создавалось поле «Фото»; теперь полей миграция не создаёт —
       несвязанный фото-объект рисует persons.photo_path (photos.photo_field_value), данные не теряются;
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
    # старый persons_touch снимаем до правок persons, новый ставим после копирования «Фото»
    # и перевода времени — иначе UPDATE fields_json сдвинет updated_at на now
    con.execute("DROP TRIGGER IF EXISTS persons_touch")
    con.execute("DROP TRIGGER IF EXISTS persons_created_local")
    con.execute(f"""CREATE TRIGGER persons_created_local AFTER INSERT ON persons
        WHEN instr(NEW.created_at, 'T') = 0 OR instr(NEW.updated_at, 'T') = 0
        BEGIN UPDATE persons SET
            created_at = CASE WHEN instr(NEW.created_at, 'T') = 0 THEN {LOCAL_NOW_SQL} ELSE NEW.created_at END,
            updated_at = CASE WHEN instr(NEW.updated_at, 'T') = 0 THEN {LOCAL_NOW_SQL} ELSE NEW.updated_at END
        WHERE id = NEW.id; END""")
    # Замечание №4 (11.11): автоматических полей нет (кроме «Дата печати»): «Фото» здесь больше не создаётся,
    # persons.photo_path и несвязанные фото-объекты остаются как есть (рендер берёт photo_path).
    _sync_photo_config_views(con)
    rows = con.execute("SELECT id, created_at, updated_at FROM persons").fetchall()
    for pid, c, u in rows:
        c2, u2 = _utc_to_local(c), _utc_to_local(u)
        if (c2, u2) != (c, u): con.execute("UPDATE persons SET created_at=?, updated_at=? WHERE id=?", (c2, u2, pid))
    con.execute(f"""CREATE TRIGGER persons_touch AFTER UPDATE ON persons WHEN NEW.updated_at = OLD.updated_at
        BEGIN UPDATE persons SET updated_at = {LOCAL_NOW_SQL} WHERE id = NEW.id; END""")

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


def _pxu(v):
    """px @ 300 DPI → единицы 0,1 мм (как px_to_units)."""
    return int(round(float(v) * 254.0 / 300))


def _style_border_v8(st: dict) -> dict:
    """Записать border_width в единицах из старого stroke_width/border_width (px). Не трогает padding/radius."""
    if not isinstance(st, dict):
        return st
    out = dict(st)
    if "border_style" in out and "border_width" in out and "stroke_width" not in out:
        return out
    src = out.get("stroke_width")
    if src is None and "border_width" in out and "border_style" not in out:
        src = out.get("border_width")
    if src not in (None, ""):
        try:
            bw = _pxu(src)
        except (TypeError, ValueError):
            return out
        out["border_width"] = bw
        if bw > 0 and "border_style" not in out:
            out["border_style"] = "solid"
    return out


def _geom_v8_obj(obj: dict) -> dict:
    if not isinstance(obj, dict):
        return obj
    o = dict(obj)
    for k in ("x", "y", "w", "h"):
        if k in o and o[k] is not None:
            try:
                o[k] = _pxu(o[k])
            except (TypeError, ValueError):
                pass
    st = o.get("style") if isinstance(o.get("style"), dict) else None
    raw = o.get("style_json")
    if st is None and raw:
        try:
            st = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            st = None
    if isinstance(st, dict):
        st = dict(st)
        for k in ("padding", "radius"):
            if st.get(k) is not None:
                try:
                    st[k] = _pxu(st[k])
                except (TypeError, ValueError):
                    pass
        st = _style_border_v8(st)
        if "style" in o and isinstance(o["style"], dict):
            o["style"] = st
        if "style_json" in o:
            o["style_json"] = json.dumps(st, ensure_ascii=False)
    return o


def _v8_units(con):
    """v8: геометрия шаблона в единицах 0,1 мм (сетка 254 DPI). Идемпотентность — только user_version."""
    con.execute("""
        UPDATE template_elements SET
          x = CAST(round(x * 254.0 / 300) AS INTEGER),
          y = CAST(round(y * 254.0 / 300) AS INTEGER),
          w = CAST(round(w * 254.0 / 300) AS INTEGER),
          h = CAST(round(h * 254.0 / 300) AS INTEGER)
    """)
    con.execute("""
        UPDATE template_elements
           SET w = CASE WHEN w = 0 AND h = 0 THEN 1 ELSE w END
         WHERE type = 'line' AND w = 0 AND h = 0
    """)
    con.execute("""
        UPDATE template_elements
           SET style_json = json_set(style_json, '$.padding',
               CAST(round(json_extract(style_json, '$.padding') * 254.0 / 300) AS INTEGER))
         WHERE json_extract(style_json, '$.padding') IS NOT NULL
    """)
    con.execute("""
        UPDATE template_elements
           SET style_json = json_set(style_json, '$.radius',
               CAST(round(json_extract(style_json, '$.radius') * 254.0 / 300) AS INTEGER))
         WHERE json_extract(style_json, '$.radius') IS NOT NULL
    """)
    for r in con.execute("SELECT id, style_json FROM templates"):
        try:
            st = json.loads(r[1] or "{}")
        except (TypeError, ValueError):
            continue
        if not isinstance(st, dict) or st.get("padding") is None:
            continue
        try:
            st = dict(st); st["padding"] = _pxu(st["padding"])
        except (TypeError, ValueError):
            continue
        con.execute("UPDATE templates SET style_json=? WHERE id=?", (json.dumps(st, ensure_ascii=False), r[0]))
    for r in con.execute("SELECT id, style_json FROM template_elements"):
        try:
            st = json.loads(r[1] or "{}")
        except (TypeError, ValueError):
            continue
        new = _style_border_v8(st)
        if new != st:
            con.execute("UPDATE template_elements SET style_json=? WHERE id=?",
                        (json.dumps(new, ensure_ascii=False), r[0]))
    row = con.execute("SELECT value FROM project_settings WHERE key='template_edit_snapshot'").fetchone()
    if row:
        try:
            snap = json.loads(row[0])
        except (TypeError, ValueError):
            snap = None
        if isinstance(snap, dict):
            els = snap.get("elements")
            if isinstance(els, list):
                snap["elements"] = [_geom_v8_obj(e) for e in els]
            tpl = snap.get("template")
            if isinstance(tpl, dict) and tpl.get("style_json"):
                try:
                    st = json.loads(tpl["style_json"])
                    if isinstance(st, dict) and st.get("padding") is not None:
                        st["padding"] = _pxu(st["padding"])
                        tpl["style_json"] = json.dumps(st, ensure_ascii=False)
                except (TypeError, ValueError):
                    pass
            con.execute("UPDATE project_settings SET value=? WHERE key='template_edit_snapshot'",
                        (json.dumps(snap, ensure_ascii=False),))
    log.info("схема v7→v8, координаты пересчитаны в 0,1 мм")


# ---------- v9 (замечание №4, 11.11): чистка автоматических полей-дублей ----------
_AUTO_PHOTO_RE = re.compile(r"^Фото(?: [0-9]+)?$")


def _is_auto_image_field(name) -> bool:
    """Авто-поле фото, которое создавала сама программа: «Фото», «Фото 2», «Фото 3», … (ensure_photo_field / v7)."""
    return bool(_AUTO_PHOTO_RE.match(str(name or "")))


def _snapshot_elements(con, tables) -> tuple[dict | None, list]:
    """Снимок правки шаблона (project_settings.template_edit_snapshot) → (snap, elements) или (None, [])."""
    if "project_settings" not in tables: return None, []
    row = con.execute("SELECT value FROM project_settings WHERE key='template_edit_snapshot'").fetchone()
    if not row: return None, []
    try: snap = json.loads(row[0])
    except (TypeError, ValueError): return None, []
    els = snap.get("elements") if isinstance(snap, dict) else None
    return (snap, els) if isinstance(els, list) else (None, [])


def _v9_unused_logo(con, tables):
    """v9, «logo» (решение Архитектора 11.11): image-поле logo (имя без учёта регистра) удаляется, ТОЛЬКО если оно
    пустое во ВСЕХ записях (нет ключа / None / '') И к нему не привязан ни один объект ни в одном шаблоне,
    включая снимок правки шаблона. Иначе не трогается. В фото-поле logo не переносится никогда."""
    _snap, snap_els = _snapshot_elements(con, tables)
    for (name,) in con.execute("SELECT name FROM person_fields WHERE data_type='image'").fetchall():
        if str(name).casefold() != "logo": continue
        if con.execute("SELECT 1 FROM template_elements WHERE field_name=? LIMIT 1", (name,)).fetchone(): continue
        if any(isinstance(e, dict) and e.get("field_name") == name for e in snap_els): continue
        if con.execute("SELECT 1 FROM persons WHERE json_valid(fields_json) AND "
                       "COALESCE(CAST(json_extract(fields_json, ?) AS TEXT), '') <> '' LIMIT 1",
                       ('$."' + str(name).replace('"', '\\"') + '"',)).fetchone(): continue
        if "person_photo_views" in tables:
            con.execute("DELETE FROM person_photo_views WHERE field_name=?", (name,))
        con.execute("DELETE FROM person_fields WHERE name=?", (name,))
        log.info("схема v8→v9: пустое неиспользуемое поле %r удалено", name)


def _v9_auto_fields(con):
    """v9 (замечание №4): чистка автоматических полей.
    A) «logo» — см. _v9_unused_logo: удаляется только пустое во всех записях и ни к чему не привязанное.
    B) «Фото N» (только data_type='image') сводятся в СВОЁ image-поле пользователя.
    Своё поле — первое image-поле не «Фото N» и не logo (sort_order, name). Своего нет → B ничего не меняет.
    Для каждого авто-поля «Фото N»:
      1) persons.fields_json: значение переносится в своё поле, только если там пусто (None/''); после переноса,
         а также если авто-значение пустое или совпадает со своим, ключ авто-поля удаляется. Оба значения
         непустые и разные → ключ авто-поля остаётся в fields_json (данные не теряются);
      2) template_elements (все шаблоны) и снимок правки шаблона: field_name авто-поля → своё поле;
      3) person_photo_views: вид фото авто-поля переходит своему полю, если у записи там вида нет;
      4) строка person_fields авто-поля удаляется.
    updated_at записей не меняется (триггер persons_touch снимается на время шага и ставится обратно).
    Шаг в общей транзакции migrate(): ошибка → ROLLBACK и MigrationError, файл не меняется."""
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    _v9_unused_logo(con, tables)
    names = [r[0] for r in con.execute("SELECT name FROM person_fields WHERE data_type='image' ORDER BY sort_order, name")]
    auto = [n for n in names if _is_auto_image_field(n)]
    own = [n for n in names if n not in auto and str(n).casefold() != "logo"]
    if not auto or not own:
        return
    target = own[0]
    trg = con.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='persons_touch'").fetchone()
    if trg: con.execute("DROP TRIGGER persons_touch")
    moved = 0
    for pid, fj in con.execute("SELECT id, fields_json FROM persons").fetchall():
        try: f = json.loads(fj or "{}")
        except (TypeError, ValueError): continue
        if not isinstance(f, dict): continue
        changed = False
        for a in auto:
            if a not in f: continue
            v, tv = f[a], f.get(target)
            if v in (None, ""):
                f.pop(a); changed = True
            elif tv in (None, ""):
                f[target] = v; f.pop(a); changed = True; moved += 1
            elif tv == v:
                f.pop(a); changed = True
        if changed:
            con.execute("UPDATE persons SET fields_json=? WHERE id=?", (json.dumps(f, ensure_ascii=False), pid))
    qm = ",".join("?" * len(auto))
    con.execute(f"UPDATE template_elements SET field_name=? WHERE field_name IN ({qm})", (target, *auto))
    if "person_photo_views" in tables:
        con.execute(f"UPDATE OR IGNORE person_photo_views SET field_name=? WHERE field_name IN ({qm})", (target, *auto))
        con.execute(f"DELETE FROM person_photo_views WHERE field_name IN ({qm})", tuple(auto))
    snap, els = _snapshot_elements(con, tables)
    if snap is not None:
        for e in els:
            if isinstance(e, dict) and e.get("field_name") in auto: e["field_name"] = target
        con.execute("UPDATE project_settings SET value=? WHERE key='template_edit_snapshot'",
                    (json.dumps(snap, ensure_ascii=False),))
    con.execute(f"DELETE FROM person_fields WHERE name IN ({qm})", tuple(auto))
    if trg: con.execute(trg[0])
    log.info("схема v8→v9: авто-поля %s сведены в «%s» (перенесено значений: %d)", auto, target, moved)


MIGRATIONS = [SCHEMA, _v2_printed_at, _v3_line, _v4_ellipse_defaults, _v5_field_types, _V6_SETTINGS, _v7_templates, _v8_units,
              _v9_auto_fields]   # индекс + 1 = user_version; str — SQL-скрипт, callable — шаг на Python
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
            try:
                con.executescript("BEGIN;\n" + step + f"\nPRAGMA user_version={i+1};\nCOMMIT;")
            except Exception as e:
                try: con.execute("ROLLBACK")
                except sqlite3.Error: pass
                raise MigrationError(f"не удалось обновить схему проекта до версии {i+1}: {e}") from e
        else:
            con.execute("BEGIN")
            try:
                step(con); con.execute(f"PRAGMA user_version={i+1}"); con.execute("COMMIT")
            except Exception as e:
                con.execute("ROLLBACK")
                raise MigrationError(f"не удалось обновить схему проекта до версии {i+1}: {e}") from e
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
