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
from badge_backend.api import MissingPhotosError  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = _api.default_db_path(ROOT)   # README: <project_dir>/project.db
ELEMENT_TYPES = ("text", "field", "photo", "image", "rect", "ellipse", "line", "qr", "barcode")   # v4: ellipse   # 'line' — по решению Архитектора (миграция Backend)
SIDES = ("front", "back")
# Русские названия типов элементов — единственный источник для подписей UI (этап 12)
TYPE_NAMES = {"field": "Поле", "text": "Текст", "photo": "Фото", "image": "Изображение", "rect": "Рамка",
              "ellipse": "Эллипс", "line": "Линия", "barcode": "Штрихкод", "qr": "QR-код"}
SIDE_NAMES = {"front": "Лицевая", "back": "Оборот"}



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
    def open_db(self, path, base_dir=None):
        if self.con is not None:
            self.con.close()
        self.db_path = path if str(path) == ":memory:" else Path(path)
        if hasattr(self, "_undo"): self.clear_history()
        self.con = _api.connect(str(self.db_path))
        # connect() применяет миграции; проверяем версию функцией Backend (без SQL в UI)
        if self.schema_version() < _db.LATEST:
            _db.migrate(self.con)
        if self.schema_version() < _db.LATEST:
            raise RuntimeError(f"БД {path}: схема v{self.schema_version()}, требуется v{_db.LATEST}")
        if base_dir:
            self.base_dir = str(base_dir)
        else:
            self.base_dir = str(Path.cwd() if str(path) == ":memory:" else Path(path).resolve().parent)

    def schema_version(self) -> int:
        return get_schema_version(self.con)

    def close(self):
        if self.con is not None:
            self.con.close(); self.con = None

    # --- записи ---
    def list_fields(self): return _api.list_fields(self.con)
    def save_photo(self, image_bytes, *, person_id=None, ext="jpg"):
        """Backend fa29d7d: файл в папку фото проекта → "photos/<name>"; с person_id сам пишет photo_path. ValueError — пусто/битые."""
        return _api.save_photo(self.con, image_bytes, person_id=person_id, ext=ext, base_dir=self.base_dir)

    def resolve_photo_path(self, person, element=None):
        """Backend 91b0208: значение привязанного image-поля, иначе persons.photo_path → абсолютный Path | None."""
        return _api.resolve_photo_path(person, element, base_dir=self.base_dir)

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
        return _api.set_background(self.con, side, color, image_path)

    # --- рендер (Backend) ---
    def render_card(self, person, side="front"):
        """person: id | dict | None. Возвращает QImage 1011x638 из badge_backend.render."""
        return pil_to_qimage(_api.render_card_db(self.con, person, side, self.base_dir))

    def render_preview(self, person, side="front", scale=0.5):
        return pil_to_qimage(_api.render_preview(self.con, person, side, scale, self.base_dir))

    # --- импорт (GUI-поток, соединение привязано к нему) ---
    def read_headers(self, path): return read_table(path)[0]
    def import_file(self, path, mapping=None, photo_dir=None, labels=None, require_photo=False, progress=None):
        return _api.import_file(self.con, path, mapping=mapping, photo_dir=photo_dir, labels=labels,
                                require_photo=require_photo, progress=progress)

    # --- экспорт / печать: подготовка в GUI-потоке ---
    # --- этап 12 (Backend v4) ---
    def query_persons(self, where=None, printed=None, only_marked=False, order_by="id"):
        return _api.query_persons(self.con, where, printed=printed, only_marked=only_marked, order_by=order_by)
    def clear_printed(self, ids): return _api.clear_printed(self.con, list(ids))
    def delete_persons(self, ids): return _api.delete_persons(self.con, list(ids))
    def backup_db(self, dest): return _api.backup_db(self.con, dest)
    def vacuum_db(self): return _api.vacuum_db(self.con)
    def compact_and_backup(self, backup_dir): return _api.compact_and_backup(self.con, backup_dir)
    def restore_from(self, backup_path):
        """Восстановить текущую БД из бэкапа: закрыть соединение → restore_db → открыть заново."""
        target = str(self.db_path)
        if target == ":memory:": raise ValueError("Временную БД в памяти восстановить нельзя")
        base = self.base_dir; self.close(); _api.restore_db(target, backup_path); self.open_db(target, base)
    def set_field_default(self, name, value): return _api.set_field_default(self.con, name, value)
    def delete_field(self, name, unlink=True): return _api.delete_field(self.con, name, unlink=unlink)
    def list_field_links(self): return _api.list_field_links(self.con)
    def link_field(self, element_id, field_name): return _api.link_field(self.con, element_id, field_name)
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
#   (белая заливка) → crop (x,y,w,h) в пикселях уже преобразованного изображения; ValueError.
# detect_face_crop(img, aspect) -> (x,y,w,h)|None; get/set_photo_edit_defaults(con[, params]) — без crop (project_settings, v6);
# apply_and_save_photo(con, source_path, params, *, person_id, field_name, base_dir) -> "photos/…" (новый файл).
PHOTO_EDIT_DEFAULTS = dict(getattr(_api, "DEFAULT_PHOTO_EDIT", None) or
                           {"brightness": 0, "contrast": 0, "scale": 100, "rotate": 0.0, "crop": None, "autoeffect": False})


def photo_edit_available(): return callable(getattr(_api, "apply_photo_edit", None))
def face_detect_available(): return callable(getattr(_api, "detect_face_crop", None))
def apply_and_save_available(): return callable(getattr(_api, "apply_and_save_photo", None))


def load_photo_available(): return callable(getattr(_api, "load_photo_for_edit", None))


def open_image(path, base_dir=None):
    """Исходник редактора: Backend load_photo_for_edit (EXIF-поворот как в apply_and_save_photo, рамка совпадает);
    нет функции → простое чтение файла без обработки."""
    fn = getattr(_api, "load_photo_for_edit", None)
    if fn is not None: return fn(path, base_dir=base_dir)
    from PIL import Image
    with Image.open(path) as im: return im.copy()


def apply_photo_edit(img, params):
    """Backend apply_photo_edit; нет функции → исходное изображение без изменений (UI сам не обрабатывает)."""
    fn = getattr(_api, "apply_photo_edit", None)
    return fn(img, dict(params)) if fn else img


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


def _bapi_apply_and_save_photo(self, source_path, params, *, person_id=None, field_name=None):
    fn = getattr(_api, "apply_and_save_photo", None)
    if fn is None: raise ValueError("применение недоступно: в Backend нет apply_and_save_photo")
    return fn(self.con, source_path, dict(params), person_id=person_id, field_name=field_name, base_dir=self.base_dir)


BackendAPI.get_photo_edit_defaults = _bapi_get_photo_edit_defaults
BackendAPI.set_photo_edit_defaults = _bapi_set_photo_edit_defaults
BackendAPI.apply_and_save_photo = _bapi_apply_and_save_photo
