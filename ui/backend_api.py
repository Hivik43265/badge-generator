"""Единственная прослойка UI -> Backend (badge_backend.api).

Только тонкие вызовы фасада: никакого SQL, хранения данных или рендера в UI.
Соединение с БД и base_dir (база относительных путей фото) держит адаптер.
"""
from __future__ import annotations
from pathlib import Path

from badge_backend import api as _api
from badge_backend import db as _db
from badge_backend.api import get_schema_version
from badge_backend import CARD_W_PX, CARD_H_PX  # noqa: F401
from badge_backend.photo_config import PhotoConfig, DEFAULT as DEFAULT_PHOTO_CONFIG  # noqa: F401
from badge_backend.services.importer import read_table, ImportReport  # noqa: F401
from badge_backend.services.headers import SYNONYMS, LABELS  # noqa: F401
from badge_backend.services.headers import SERVICE_KEYS as _SERVICE_KEYS
from badge_backend.services.sources import PROJECT_COLS as _PROJECT_COLS
# служебные колонки по списку Backend (не создаются как поля)
SERVICE_COLUMNS = frozenset(_SERVICE_KEYS) | frozenset(_PROJECT_COLS)
from badge_backend.api import MissingPhotosError  # noqa: F401
from badge_backend.api import (
    ProjectLockedError, RecoverableProjectError, ProjectSaveError,
    UnsavedChangesError, TemplateEditActiveError,
    open_project, create_project, recover, list_recoverable_sessions,
)  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = _api.default_db_path(ROOT)   # README: <project_dir>/project.db
ELEMENT_TYPES = ("text", "field", "photo", "image", "rect", "ellipse", "line", "qr", "barcode")   # v4: ellipse   # 'line' — по решению Архитектора (миграция Backend)
SIDES = ("front", "back")
# Русские названия типов элементов — единственный источник для подписей UI (этап 12)
TYPE_NAMES = {"field": "Поле", "text": "Текст", "photo": "Фото", "image": "Изображение", "rect": "Рамка",
              "ellipse": "Эллипс", "line": "Линия", "barcode": "Штрихкод", "qr": "QR-код"}
SIDE_NAMES = {"front": "Лицевая", "back": "Оборот"}


# --- координаты 0.1 мм (контракт v8). На 583e88c имён ещё нет — fallback как сейчас (px). ---
import badge_backend as _badge_pkg

def _unit_attr(name, default=None):
    """Сначала пакет badge_backend, затем badge_backend.api; иначе default."""
    if hasattr(_badge_pkg, name):
        return getattr(_badge_pkg, name)
    return getattr(_api, name, default)

GRID_DPI = _unit_attr("GRID_DPI", 254)
UNIT_MM = _unit_attr("UNIT_MM", 0.1)
CARD_W_UNITS = _unit_attr("CARD_W_UNITS", 856)
CARD_H_UNITS = _unit_attr("CARD_H_UNITS", 540)


def uses_grid_units():
    """True, когда Backend отдал units_to_px — холст и запись в 0.1 мм."""
    return callable(_unit_attr("units_to_px"))


def units_to_px(u, dpi=300):
    fn = _unit_attr("units_to_px")
    if callable(fn):
        try:
            return fn(u, dpi)
        except TypeError:
            return fn(u, dpi=dpi)
    return int(round(float(u)))


def px_to_units(px, dpi=300):
    fn = _unit_attr("px_to_units")
    if callable(fn):
        try:
            return fn(px, dpi)
        except TypeError:
            return fn(px, dpi=dpi)
    return int(round(float(px)))


def units_to_mm(u):
    fn = _unit_attr("units_to_mm")
    if callable(fn):
        return float(fn(u))
    # fallback: значение в записи — пиксели @ 300 DPI
    return float(u) * 25.4 / 300.0


def mm_to_units(mm):
    fn = _unit_attr("mm_to_units")
    if callable(fn):
        return fn(mm)
    return int(round(float(mm) * 300.0 / 25.4))


def px_to_mm(px, dpi=300):
    fn = _unit_attr("px_to_mm")
    if callable(fn):
        try:
            return float(fn(px, dpi))
        except TypeError:
            return float(fn(px, dpi=dpi))
    return float(px) * 25.4 / float(dpi)


def scene_width():
    return int(CARD_W_UNITS) if uses_grid_units() else int(CARD_W_PX)


def scene_height():
    return int(CARD_H_UNITS) if uses_grid_units() else int(CARD_H_PX)


def stored_to_mm(v):
    """x/y/w/h из записи → мм для спинбоксов."""
    return units_to_mm(v)


def mm_to_stored(mm):
    """мм со спинбокса → целое в записи (единицы 0.1 мм или px)."""
    return int(round(mm_to_units(mm)))


def snap_scene(v):
    """Шаг перетаскивания: 1 единица сцены (0.1 мм при API, иначе 1 px)."""
    return int(round(float(v)))


def update_element_style_available():
    return callable(getattr(_api, "update_element_style", None))


def list_fonts():
    """Семейства, которые умеет загрузить рендерер (контракт: api.list_fonts() -> list[str]).

    list_font_families() — алиас. Пока Backend не отдал list_fonts, берём текущий
    list_font_families. Свой список (QFontDatabase и т.п.) не строим.
    """
    fn = getattr(_api, "list_fonts", None)
    if not callable(fn):
        fn = getattr(_api, "list_font_families", None)
    if not callable(fn):
        return []
    return list(fn())


# Класс ошибки миграции схемы/координат (v8: файл не меняется, .bak сохраняется).
MigrationError = getattr(_db, "MigrationError", None) or getattr(_api, "MigrationError", None)


def format_schema_migration_error(exc):
    """Текст ошибки миграции при открытии проекта, либо None, если это не она."""
    cls = MigrationError
    if cls is not None and isinstance(exc, cls):
        return str(exc)
    return None




def pil_to_qimage(img):
    """PIL.Image (результат рендера Backend) -> QImage. Только конвертация, без рисования."""
    from PyQt6.QtGui import QImage
    img = img.convert("RGB")
    data = img.tobytes("raw", "RGB")
    return QImage(data, img.width, img.height, 3 * img.width, QImage.Format.Format_RGB888).copy()


import inspect as _inspect
_UPSERT_HAS_TYPE = "data_type" in _inspect.signature(_api.upsert_field).parameters
# D24: типы данных полей (значения data_type в Backend) → подписи UI
FIELD_TYPES = [("text", "Строка"), ("number", "Число"), ("date", "Дата"), ("image", "Изображение"), ("bool", "Да/Нет")]
FIELD_TYPE_NAMES = dict(FIELD_TYPES)


def field_type(f):
    """Тип поля из list_fields(); нет data_type в Backend → «text» (Строка)."""
    t = (f or {}).get("data_type") or "text"
    return t if t in FIELD_TYPE_NAMES else "text"


def display_value(data_type, value):
    """Показ значения: даты ДД.ММ.ГГГГ, булево Да/Нет — только через badge_backend.fields.format_value."""
    if value in (None, ""): return ""
    try:
        from badge_backend.fields import format_value
        return str(format_value(data_type or "text", value))
    except Exception:  # noqa: BLE001
        return str(value)


def new_field_name(label, existing):
    from badge_backend.services.headers import slugify
    base = slugify(label) or "field"; n, i = base, 2
    while n in existing: n, i = f"{base}_{i}", i + 1
    return n


def person_caption(api, p):
    """«#id <первые два непустых поля в порядке list_fields()>» — без жёстко заданных ключей (D24)."""
    if not p: return ""
    vals = [str(p["fields"].get(f["name"]) or "") for f in api.list_fields()]
    return f"#{p['id']} " + " ".join([v for v in vals if v][:2])


class BackendAPI:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH, base_dir: str | Path | None = None):
        self.con = None
        self.open_db(db_path, base_dir)

    # --- БД ---
    def open_db(self, path, base_dir=None, *, recover=None):
        """Открыть/создать проект через ProjectSession: self.con — рабочая копия (session.con).
        recover=None и есть несохранённая копия → RecoverableProjectError (диалог в UI).
        MigrationError (миграция схемы) пробрасывается как есть — UI показывает текст ошибки;
        файл не изменён, .bak сохраняется Backend'ом."""
        if str(path) == ":memory:":
            sess = open_project(":memory:")
        else:
            pth = Path(path)
            sess = create_project(pth) if not pth.exists() else open_project(pth, recover=recover)
        self.adopt_session(sess)
        if base_dir: self.base_dir = str(base_dir)
        if self.schema_version() < _db.LATEST:
            raise RuntimeError(f"БД {path}: схема v{self.schema_version()}, требуется v{_db.LATEST}")

    def adopt_session(self, session):
        """Подменить сессию (после recover / save_as / открытия). Старую закрывает без записи."""
        old = getattr(self, "session", None)
        self.session = session
        self.con = session.con
        if session.source_path is not None:
            self.db_path = session.source_path
        else:
            name = getattr(session, "suggested_name", None)
            self.db_path = Path(name) if name else Path(":memory:")
        self.base_dir = str(session.base_dir)
        if hasattr(self, "_undo"): self.clear_history()
        if old is not None and old is not session:
            self._release_session(old, persist=False)

    def schema_version(self) -> int:
        return get_schema_version(self.con)

    def _release_session(self, sess, *, persist=False):
        """Снять сессию. persist=True — явно записать исходник; по умолчанию не пишет
        (запись только по «Сохранить», UI спрашивает до замены сессии)."""
        if sess is None: return
        try:
            if persist and sess.con is not None and sess.source_path is not None and sess.is_dirty():
                try:
                    sess.save()
                except TemplateEditActiveError:
                    sess.save(commit_template=True)
        except Exception:
            pass
        try:
            sess.discard()
        except Exception:
            if sess.con is not None:
                try: sess.con.close()
                except Exception: pass

    def close(self):
        sess = getattr(self, "session", None)
        if sess is not None:
            self._release_session(sess, persist=False)
            self.session = None; self.con = None; return
        if self.con is not None:
            self.con.close(); self.con = None

    def import_smartid_as_new_project(self, path):
        """Открыть .csd/.csp: свой .csp — сохранённый проект из .db, чужой — импорт.

        Предыдущую сессию закрывает без записи. Возвращает (session, result);
        result['kind'] == 'own_project' | 'import', плюс поля import_smartid.
        """
        return self.open_csd_or_csp(path)

    def open_csd_or_csp(self, path):
        """То же, что import_smartid_as_new_project (единый фасад открытия)."""
        session, result = _api.open_csd_or_csp(path)
        self.adopt_session(session)
        return session, result

    def create_project(self, path):
        """Создать проект-тройку (.csp + .csd + .db) и открыть сессию. Файл есть → FileExistsError."""
        sess = _api.create_project(path)
        self.adopt_session(sess)
        return sess

    def save(self, *, commit_template=False):
        """session.save(); в результате есть dropped (что не попало в .csd)."""
        return self.session.save(commit_template=commit_template)

    def save_as(self, dest, *, overwrite=False, commit_template=False):
        """session.save_as(); тройку пишет Backend. Результат содержит dropped."""
        r = self.session.save_as(dest, overwrite=overwrite, commit_template=commit_template)
        self.adopt_session(self.session)
        return r

    # --- записи ---
    def list_fields(self): return _api.list_fields(self.con)
    def list_image_fields(self): return _api.list_image_fields(self.con)   # замечание №4: image-поля для привязки фото
    def save_photo(self, image_bytes, *, person_id=None, ext="jpg"):
        """Backend fa29d7d: файл в папку фото проекта → "photos/<name>"; с person_id сам пишет photo_path. ValueError — пусто/битые."""
        return _api.save_photo(self.con, image_bytes, person_id=person_id, ext=ext, base_dir=self.base_dir)

    def resolve_photo_path(self, person, element=None, base_dir=None):
        """Backend 91b0208: значение привязанного image-поля, иначе persons.photo_path → абсолютный Path | None."""
        return _api.resolve_photo_path(person, element, base_dir=base_dir or self.base_dir)

    def photo_value(self, person, element=None):
        """Относительное значение фото для показа (image-поле элемента или photo_path)."""
        fn = element if isinstance(element, str) else (element or {}).get("field_name")
        v = ((person or {}).get("fields") or {}).get(fn) if fn else None
        return v or (person or {}).get("photo_path") or ""

    def auto_match(self, columns, mapping=None):
        return _api.auto_match(columns, mapping, fields=self.con)

    def set_field_type(self, name, data_type):
        return _api.set_field_type(self.con, name, data_type)

    def validate_fields(self, fields):
        return _api.validate_fields(self.con, fields)

    def upsert_field(self, name, label, sort_order=0, data_type=None):
        """D24: data_type передаётся, только если Backend его принимает (иначе — тип «Строка» по умолчанию)."""
        if data_type is not None and _UPSERT_HAS_TYPE:
            return _api.upsert_field(self.con, name, label, sort_order, data_type=data_type)
        return _api.upsert_field(self.con, name, label, sort_order)
    def list_persons(self, only_marked=False): return _api.list_persons(self.con, only_marked)
    def get_person(self, pid): return _api.get_person(self.con, pid)
    def create_person(self, fields, photo_path=None, photo_config=None, print_mark=0):
        return _api.create_person(self.con, fields, photo_path, photo_config, print_mark)
    def update_person(self, pid, **kw): return _api.update_person(self.con, pid, **kw)
    def delete_person(self, pid): return _api.delete_person(self.con, pid)
    def update_photo_config(self, pid, cfg): return _api.update_photo_config(self.con, pid, cfg)
    def set_print_mark(self, ids, value: bool):
        """Флаг «к печати» (print_mark), printed_at не меняется."""
        return _api.set_print_mark(self.con, list(ids), bool(value))
    def mark_printed(self, ids):
        """«Напечатано»: print_mark=0 и printed_at=now одной транзакцией."""
        return _api.mark_printed(self.con, list(ids))

    # --- шаблон ---
    def list_elements(self, side=None): return _api.list_elements(self.con, side)
    # Элементы шаблона + история для «Отменить/Повторить» (только вызовы фасада, без SQL)
    _EL_KEYS = ("type", "x", "y", "w", "h", "field_name", "static_value", "style", "side", "z_order")

    def _hist(self):
        if not hasattr(self, "_undo"): self._undo, self._redo, self._ids, self._replaying = [], [], {}, False
        return self._undo

    def _id(self, eid): self._hist(); return self._ids.get(eid, eid)

    def _el(self, eid): return next((e for e in _api.list_elements(self.con) if e["id"] == self._id(eid)), None)

    def _record(self, op):
        self._hist()
        if not self._replaying: self._undo.append(op); self._redo.clear()

    def create_element(self, **kw):
        eid = _api.create_element(self.con, **kw); self._record(("create", eid, dict(kw))); return eid

    def update_element(self, eid, **changes):
        old = self._el(eid); r = _api.update_element(self.con, self._id(eid), **changes)
        if old: self._record(("update", eid, {k: old.get(k) for k in changes}, dict(changes)))
        return r

    def delete_element(self, eid):
        old = self._el(eid); r = _api.delete_element(self.con, self._id(eid))
        if old: self._record(("delete", eid, {k: old.get(k) for k in self._EL_KEYS}))
        return r

    def can_undo(self): return bool(self._hist())
    def can_redo(self): self._hist(); return bool(self._redo)

    def _apply(self, op, inverse):
        kind, eid = op[0], op[1]; self._replaying = True
        try:
            if (kind == "create") == inverse:          # отмена создания / повтор удаления
                _api.delete_element(self.con, self._id(eid))
            elif kind in ("create", "delete"):         # повтор создания / отмена удаления
                data = op[2]; self._ids[eid] = _api.create_element(self.con, **data)
            else:
                _api.update_element(self.con, self._id(eid), **(op[2] if inverse else op[3]))
        finally:
            self._replaying = False

    def undo(self):
        if not self.can_undo(): return False
        op = self._undo.pop(); self._apply(op, True); self._redo.append(op); return True

    def redo(self):
        if not self.can_redo(): return False
        op = self._redo.pop(); self._apply(op, False); self._undo.append(op); return True

    def clear_history(self): self._hist(); self._undo.clear(); self._redo.clear(); self._ids.clear()
    def get_background(self, side): return _api.get_background(self.con, side)
    def set_background(self, side, color="#FFFFFF", image_path=None):
        """Фон СТРАНИЦЫ (не заливка объекта). Не смешивать с style.bg_color."""
        return _api.set_background(self.con, side, color, image_path)

    def update_element_style(self, eid, **changes):
        """Слить ключи стиля. Нет функции в Backend → None (вызывающий держит в памяти)."""
        fn = getattr(_api, "update_element_style", None)
        if not callable(fn):
            return None
        old = self._el(eid)
        r = fn(self.con, self._id(eid), **changes)
        if old is not None:
            self._record(("update", eid, {"style": old.get("style")}, {"style": r}))
        return r

    # --- рендер (Backend) ---
    def render_card(self, person, side="front"):
        """person: id | dict | None. Возвращает QImage 1011x638 из badge_backend.render."""
        return pil_to_qimage(_api.render_card_db(self.con, person, side, self.base_dir))

    def render_preview(self, person, side="front", scale=0.5):
        return pil_to_qimage(_api.render_preview(self.con, person, side, scale, self.base_dir))

    def gather_render_args(self, person, side="front", *, field_names=False):
        """GUI-поток: прочитать person / элементы / фон. Результат — аргументы render_card_mem без con.
        Замечание №5а: field_names (при person=None) уходит в payload — воркер рисует как render_card_db.
        По умолчанию False (пустой шаблон); названия полей — только если редактор явно передал field_names=True."""
        from badge_backend.render import load_elements, load_background, load_photo_views
        if isinstance(person, int):
            row = _api.get_person(self.con, person)
            if row is None:
                raise KeyError(f"person {person} не найден")
            person = dict(row)
            if person.get("id") is not None:
                person["photo_views"] = load_photo_views(self.con, person["id"])
        elif person is not None:
            person = dict(person)
            if "photo_views" not in person and person.get("id") is not None:
                person["photo_views"] = load_photo_views(self.con, person["id"])
        return {"person": person, "elements": load_elements(self.con, side), "side": side,
                "background": load_background(self.con, side), "base_dir": self.base_dir,
                "field_names": bool(field_names)}

    # --- импорт (GUI-поток, соединение привязано к нему) ---
    def read_headers(self, path): return read_table(path)[0]

    # --- экспорт / печать: подготовка в GUI-потоке ---
    # --- этап 12 (Backend v4) ---
    def query_persons(self, where=None, printed=None, only_marked=False, order_by="id"):
        return _api.query_persons(self.con, where, printed=printed, only_marked=only_marked, order_by=order_by)
    def clear_printed(self, ids): return _api.clear_printed(self.con, list(ids))
    def delete_persons(self, ids): return _api.delete_persons(self.con, list(ids))
    def vacuum_db(self): return _api.vacuum_db(self.con)
    def compact_and_backup(self, backup_dir): return _api.compact_and_backup(self.con, backup_dir)
    def restore_from(self, backup_path):
        """Восстановить в рабочую копию (исходник не трогать, dirty=True)."""
        sess = getattr(self, "session", None)
        if sess is not None:
            sess.restore_from(backup_path); self.con = sess.con; return
        target = str(self.db_path)
        if target == ":memory:": raise ValueError("Временную БД в памяти восстановить нельзя")
        base = self.base_dir; self.close(); _api.restore_db(target, backup_path); self.open_db(target, base)
    def set_field_default(self, name, value): return _api.set_field_default(self.con, name, value)
    def delete_field(self, name, unlink=True): return _api.delete_field(self.con, name, unlink=unlink)
    def list_field_links(self): return _api.list_field_links(self.con)
    def link_field(self, element_id, field_name, *, side="front"):
        """element_id=None → Backend создаёт объект на стороне side и сразу связывает (этап 15)."""
        return _api.link_field(self.con, element_id, field_name, side=side)
    def unlink_field(self, element_id, static_value=None): return _api.unlink_field(self.con, element_id, static_value)

    def missing_photos(self, ids=None): return _api.missing_photos(self.con, ids, self.base_dir)
    def snapshot(self, ids=None, sides=SIDES): return _api.snapshot(self.con, ids, tuple(sides))


# --- выполнение по snapshot: без соединения, безопасно в рабочем потоке ---
def export_png_from_snapshot(snap, out_dir, base_dir, progress=None, allow_missing_photo=False):
    return _api.export_png_from_snapshot(snap, out_dir, base_dir, progress=progress, allow_missing_photo=allow_missing_photo)


def export_pdf_from_snapshot(snap, out_path, base_dir, progress=None, allow_missing_photo=False):
    return _api.export_pdf_from_snapshot(snap, out_path, base_dir, progress=progress, allow_missing_photo=allow_missing_photo)


def print_snapshot(snap, printer, base_dir, progress=None, allow_missing_photo=False):
    return _api.print_snapshot(snap, printer, base_dir, progress=progress, allow_missing_photo=allow_missing_photo)


# ---------------- D19: согласованность полей (адаптер; в Backend нужна check_field_consistency) ----------------
def field_desync(api):
    """{"person_keys": [...], "template_fields": [...]} — ключи записей без person_fields и field_name шаблона без поля.
    Считается по публичным list_fields/list_persons/list_elements (без SQL)."""
    names = {f["name"] for f in api.list_fields()}
    keys = sorted({k for p in api.list_persons() for k in (p.get("fields") or {}) if k not in names})
    tmpl = sorted({e["field_name"] for e in api.list_elements() if e.get("field_name") and e["field_name"] not in names})
    return {"person_keys": keys, "template_fields": tmpl}


def desync_text(d):
    parts = []
    if d["template_fields"]: parts.append("в шаблоне есть поля без person_fields: " + ", ".join(d["template_fields"]))
    if d["person_keys"]: parts.append("в записях есть ключи без person_fields: " + ", ".join(d["person_keys"]))
    return ("⚠ Рассинхрон полей: " + "; ".join(parts)) if parts else ""
# ---------------- Этап 13: источники импорта / экспорт данных (Backend: services.sources / table_export) ----------------
from badge_backend.api import XLS_MAX_ROWS, Sheet  # noqa: E402,F401
IMPORT_FORMATS = "Источники (*.xlsx *.xlsm *.xls *.csv *.txt *.db *.sqlite *.sqlite3)"
DATA_FORMATS = [("xlsx", "Excel (.xlsx)"), ("xls", "Excel 97–2003 (.xls)"), ("csv", "CSV (.csv)"), ("db", "База проекта (.db)")]
SHEET_KINDS = {"xlsx": "лист Excel", "xls": "лист Excel 97–2003", "csv": "CSV", "project": "БД проекта", "sqlite": "таблица SQLite"}


def open_source(path): return _api.open_source(path)
def read_rows(sheet, header=True, limit=None): return _api.read_rows(sheet, header=header, limit=limit)
def save_mapping(path, mapping, columns=None): return _api.save_mapping(path, mapping or {}, columns=columns)
def load_mapping(path): return _api.load_mapping(path)


def _bapi_import_rows(self, sheet, mapping=None, **kw):
    kw.setdefault("photo_dir", None)
    return _api.import_rows(self.con, sheet, mapping, **kw)


def _bapi_export_persons(self, path, fmt=None, ids=None, **kw):
    return _api.export_persons(self.con, path, fmt, ids, **kw)


def _bapi_auto_match_full(self, columns, mapping=None):
    return _api.auto_match(columns, mapping, fields=self.con)


BackendAPI.import_rows = _bapi_import_rows
BackendAPI.export_persons = _bapi_export_persons


# ---------------- Этап 14: редактор фото — Backend ee79d16 (badge_backend.api) ----------------
# apply_photo_edit(img, params) -> Image; порядок autoeffect → яркость → контраст → масштаб → поворот по часовой
#   (белая заливка) → crop (x,y,w,h) в пикселях изображения ПОСЛЕ EXIF-поворота, масштаба и вращения
#   (не в пикселях исходного файла); ValueError.
# detect_face_crop(img, aspect) -> (x,y,w,h)|None; get/set_photo_edit_defaults(con[, params]) — без crop (project_settings, v6);
# apply_and_save_photo(con, source_path, params, *, person_id, field_name, base_dir) -> "photos/…" (новый файл).
PHOTO_EDIT_DEFAULTS = dict(getattr(_api, "DEFAULT_PHOTO_EDIT", None) or
                           {"brightness": 0, "contrast": 0, "scale": 100, "rotate": 0.0, "crop": None, "autoeffect": False})


def photo_edit_available(): return callable(getattr(_api, "apply_photo_edit", None))
def face_detect_available(): return callable(getattr(_api, "detect_face_crop", None))
def apply_and_save_available(): return callable(getattr(_api, "apply_and_save_photo", None))


def load_photo_available(): return callable(getattr(_api, "load_photo_for_edit", None))


def open_image(path, base_dir=None):
    """Исходник редактора — только Backend load_photo_for_edit (EXIF-поворот как в apply_and_save_photo, рамка совпадает).
    Нет функции → LookupError(«Редактор недоступен: нет load_photo_for_edit»); битый/нет файла → ValueError Backend."""
    fn = getattr(_api, "load_photo_for_edit", None)
    if fn is None: raise LookupError("Редактор недоступен: нет load_photo_for_edit")
    return fn(path, base_dir=base_dir)


def apply_photo_edit(img, params):
    """Backend apply_photo_edit; нет функции → исходное изображение без изменений (UI сам не обрабатывает)."""
    fn = getattr(_api, "apply_photo_edit", None)
    return fn(img, dict(params)) if fn else img


def render_card_mem(person, elements, side="front", background=None, base_dir=None, field_names=False):
    """Чистый Backend render_card: без соединения SQLite (для воркера превью).
    Замечание №5а: по умолчанию field_names=False — как render_card_db без флага (пустой шаблон).
    person=None и явный field_names=True → тот же вид, что render_card_db(con, None, field_names=True):
    привязанный текст — названием поля, фото — заглушкой с названием (элементы из load_elements, ключ field_label)."""
    if person is None and field_names:
        from badge_backend.render import _field_name_view
        elements = _field_name_view(elements)
    return _api.render_card(person, elements, side, background, base_dir)


PREVIEW_MAX_SIDE = 800


def preview_photo_edit(img, params, max_side=None, *, path=None, base_dir=None):
    """Превью редактора: apply_photo_edit по уменьшенной копии (макс. сторона max_side).

    Возвращает (image, k), где координаты crop на превью = crop полного кадра * k.
    Уменьшение — Backend load_photo_for_preview(path, max_side, base_dir);
    нет функции — уменьшенный scale в apply_photo_edit (без Pillow в UI).
    """
    max_side = int(max_side or PREVIEW_MAX_SIDE)
    params = {**dict(params or {}), "crop": None}
    fn = getattr(_api, "load_photo_for_preview", None)
    src_w = getattr(img, "width", 0) or 0
    if fn is not None and path:
        work = fn(path, max_side=max_side, base_dir=base_dir)
        out = apply_photo_edit(work, params)
        k = work.width / src_w if src_w else 1.0
        return out, (k if k > 0 else 1.0)
    src_max = max(img.width, img.height) or 1
    sc = float(params.get("scale") or 100)
    out_max = src_max * sc / 100.0
    if out_max <= max_side:
        return apply_photo_edit(img, params), 1.0
    preview_scale = max(10, min(400, round(max_side / src_max * 100)))
    k = (preview_scale / sc) if sc else 1.0
    return apply_photo_edit(img, {**params, "scale": int(preview_scale)}), k


def detect_face_crop(img, aspect):
    fn = getattr(_api, "detect_face_crop", None)
    return fn(img, aspect) if fn else None


def image_png_bytes(img):
    import io
    b = io.BytesIO(); img.save(b, "PNG"); return b.getvalue()


def _bapi_get_photo_edit_defaults(self):
    """Умолчания редактора фото проекта (Backend); нет функции/ошибка → DEFAULT_PHOTO_EDIT."""
    fn = getattr(_api, "get_photo_edit_defaults", None)
    try: return {**PHOTO_EDIT_DEFAULTS, **(fn(self.con) if fn else {}), "crop": None}
    except Exception: return dict(PHOTO_EDIT_DEFAULTS)  # noqa: BLE001


def _bapi_set_photo_edit_defaults(self, params):
    fn = getattr(_api, "set_photo_edit_defaults", None)
    if fn is None: raise ValueError("сохранение умолчаний недоступно: в Backend нет set_photo_edit_defaults")
    return fn(self.con, {**params, "crop": None})


def _bapi_apply_and_save_photo(self, source_path, params, *, person_id=None, field_name=None, size=None, target_field=None):
    """D44/D45: target_field (имя image-поля) и size=(w, h) передаются Backend — размер результата считает Backend."""
    kw = {k: v for k, v in (("size", size), ("target_field", target_field)) if v is not None}
    fn = getattr(_api, "apply_and_save_photo", None)
    if fn is None: raise ValueError("применение недоступно: в Backend нет apply_and_save_photo")
    return fn(self.con, source_path, dict(params), person_id=person_id, field_name=field_name, base_dir=self.base_dir, **kw)


def _backend_fn(name):
    """Функция Backend этапа 14: сначала badge_backend.api, затем badge_backend.services.photo_edit; нет → None."""
    fn = getattr(_api, name, None)
    if fn is None:
        try:
            from badge_backend.services import photo_edit as _pe
            fn = getattr(_pe, name, None)
        except ImportError:
            fn = None
    return fn if callable(fn) else None


NO_TARGET_FN = "Нет функции Backend для пропорций"
NO_TARGET = "К полю не привязан фото-элемент шаблона"


def _bapi_photo_edit_target(self, field_name=None, *, element_id=None, field=None):
    """Backend photo_edit_target(con, field_name=None, *, element_id=None, field=None).
    element_id — фото-элемент активного шаблона (двойной щелчок). field_name/field устарели.
    → {"aspect", "size", "width_mm", "height_mm", "element_id"} | None. Нет функции → LookupError."""
    fn = _backend_fn("photo_edit_target")
    if fn is None: raise LookupError(NO_TARGET_FN)
    try:
        return fn(self.con, field_name, element_id=element_id, field=field)
    except TypeError:
        return fn(self.con, field_name)


def _bapi_discard_photo(self, rel_path):
    """Backend discard_photo(con, rel_path | [paths], base_dir) → bool | список удалённых (только photos/ без ссылок). Нет → None."""
    fn = _backend_fn("discard_photo")
    return fn(self.con, rel_path, base_dir=self.base_dir) if fn else None


def _bapi_photo_session(self):
    """D43: Backend PhotoSession(con, base_dir) — учёт фото, созданных в форме записи (.save_photo / .apply_and_save_photo /
    .track; «Отмена» → .discard(), «Сохранить» → .commit()). Нет класса в Backend → None (форма работает без учёта)."""
    cls = _backend_fn("PhotoSession")
    return cls(self.con, self.base_dir) if cls else None


BackendAPI.photo_session = _bapi_photo_session
BackendAPI.photo_edit_target = _bapi_photo_edit_target
BackendAPI.discard_photo = _bapi_discard_photo
BackendAPI.get_photo_edit_defaults = _bapi_get_photo_edit_defaults
BackendAPI.set_photo_edit_defaults = _bapi_set_photo_edit_defaults
BackendAPI.apply_and_save_photo = _bapi_apply_and_save_photo


def _selftest_face_crop(aspect=0.778):
    """D47 (приватно, для --self-test): ассет Backend badge_backend/assets/selftest_face.jpg рядом с badge_backend.__file__
    (работает и в PyInstaller: <_MEIPASS>/badge_backend/…) → load_photo_for_edit → detect_face_crop(img, aspect).
    → (crop | None, путь). Любые ошибки (нет ассета/функции, RuntimeError без каскада) пробрасываются вызывающему."""
    import badge_backend
    path = Path(badge_backend.__file__).resolve().parent / "assets" / "selftest_face.jpg"
    if not path.is_file(): raise FileNotFoundError(f"нет ассета самотеста: {path}")
    load, det = getattr(_api, "load_photo_for_edit", None), getattr(_api, "detect_face_crop", None)
    if not callable(load) or not callable(det): raise LookupError("в Backend нет load_photo_for_edit/detect_face_crop")
    return det(load(str(path)), aspect), str(path)


# ---------------- Этап 15: шаблоны, поиск, вид фото ----------------
def apply_photo_view(src, w, h, params=None):
    """Тот же путь, что render_photo(..., size=(w,h)): apply_photo_view Backend (карточка)."""
    fn = getattr(_api, "apply_photo_view", None)
    if fn is None:
        from badge_backend.services.photo_edit import apply_photo_view as fn
    return fn(src, int(w), int(h), params)


def portrait_params(img, aspect, params=None):
    fn = getattr(_api, "portrait_params", None)
    return fn(img, aspect, params) if fn else None

def autoeffect_params(img, params=None):
    fn = getattr(_api, "autoeffect_params", None)
    return fn(img, params) if fn else None


def _bapi_list_templates(self): return _api.list_templates(self.con)
def _bapi_get_template(self, template_id=None): return _api.get_template(self.con, template_id)
def _bapi_get_active_template(self): return _api.get_active_template(self.con)
def _bapi_set_active_template(self, template_id): return _api.set_active_template(self.con, template_id)
def _bapi_create_template(self, name, *, copy_from=None, activate=False):
    return _api.create_template(self.con, name, copy_from=copy_from, activate=activate)
def _bapi_rename_template(self, template_id, name): return _api.rename_template(self.con, template_id, name)
def _bapi_delete_template(self, template_id): return _api.delete_template(self.con, template_id)
def _bapi_get_template_style(self, template_id=None): return _api.get_template_style(self.con, template_id)
def _bapi_set_template_style(self, style, template_id=None): return _api.set_template_style(self.con, style, template_id)
def _bapi_list_fonts(self):
    return list_fonts()

def _bapi_list_font_families(self):
    """Алиас list_fonts() (контракт)."""
    return list_fonts()
def _bapi_get_template_edit_state(self): return _api.get_template_edit_state(self.con)
def _bapi_begin_template_edit(self, template_id=None):
    return _api.begin_template_edit(self.con, template_id)
def _bapi_commit_template_edit(self):
    return _api.commit_template_edit(self.con)
def _bapi_cancel_template_edit(self):
    r = _api.cancel_template_edit(self.con); self.clear_history(); return r
def _bapi_parse_search(self, text): return _api.parse_search(text, self.con)
def _bapi_search_persons(self, text, **kw): return _api.search_persons(self.con, text, **kw)
def _bapi_get_photo_view(self, person_id, field_name=None): return _api.get_photo_view(self.con, person_id, field_name)
def _bapi_set_photo_view(self, person_id, params, field_name=None): return _api.set_photo_view(self.con, person_id, params, field_name)
def _bapi_export_template(self, dest, template_id=None, *, overwrite=True):
    return _api.export_template(self.con, dest, template_id, overwrite=overwrite)
def _bapi_import_template(self, src):
    return _api.import_template(self.con, src)
def _bapi_preview_template_file(self, src):
    return _api.preview_template_file(src, self.con)
def _bapi_get_photo_frame_spec(self, field=None, *, element_id=None, field_name=None):
    fn = getattr(_api, "get_photo_frame_spec", None)
    if fn is None: raise LookupError("нет get_photo_frame_spec")
    return fn(self.con, field, element_id=element_id, field_name=field_name)
def _bapi_get_photo_editor_state(self, person_id, element_id=None):
    """Backend get_photo_editor_state(con, person_id, element_id) → {params, frame, photo_path, element_id, field_name}.
    Рамка crop в params — в пикселях после EXIF, масштаба и вращения. Нет функции → None."""
    fn = getattr(_api, "get_photo_editor_state", None)
    return fn(self.con, person_id, element_id) if fn else None
def _bapi_render_photo(self, person_id, field_name=None, *, size=None):
    """Backend render_photo(con, person_id, field_name, size=) — вид записи в рамку size (как на карточке)."""
    fn = getattr(_api, "render_photo", None)
    if fn is None: raise LookupError("нет render_photo")
    return fn(self.con, person_id, field_name, size=size, base_dir=self.base_dir)


def setup_printer(printer):
    """Страница CR80 на QPrinter до QPrintDialog (badge_backend.services.print_service)."""
    from badge_backend.services.print_service import setup_printer as _sp
    return _sp(printer)


def pdf_pages_are_cr80(path, tol=0.15):
    from badge_backend.services.print_service import pdf_pages_are_cr80 as _fn
    return _fn(path, tol)


def pdf_page_sizes_mm(path):
    from badge_backend.services.print_service import pdf_page_sizes_mm as _fn
    return _fn(path)


BackendAPI.list_templates = _bapi_list_templates
BackendAPI.get_template = _bapi_get_template
BackendAPI.get_active_template = _bapi_get_active_template
BackendAPI.set_active_template = _bapi_set_active_template
BackendAPI.create_template = _bapi_create_template
BackendAPI.rename_template = _bapi_rename_template
BackendAPI.delete_template = _bapi_delete_template
BackendAPI.get_template_style = _bapi_get_template_style
BackendAPI.set_template_style = _bapi_set_template_style
BackendAPI.list_fonts = _bapi_list_fonts
BackendAPI.list_font_families = _bapi_list_font_families
BackendAPI.get_template_edit_state = _bapi_get_template_edit_state
BackendAPI.begin_template_edit = _bapi_begin_template_edit
BackendAPI.commit_template_edit = _bapi_commit_template_edit
BackendAPI.cancel_template_edit = _bapi_cancel_template_edit
BackendAPI.parse_search = _bapi_parse_search
BackendAPI.search_persons = _bapi_search_persons
BackendAPI.get_photo_view = _bapi_get_photo_view
BackendAPI.set_photo_view = _bapi_set_photo_view
BackendAPI.get_photo_frame_spec = _bapi_get_photo_frame_spec
BackendAPI.get_photo_editor_state = _bapi_get_photo_editor_state
BackendAPI.render_photo = _bapi_render_photo
BackendAPI.export_template = _bapi_export_template
BackendAPI.import_template = _bapi_import_template
BackendAPI.preview_template_file = _bapi_preview_template_file
