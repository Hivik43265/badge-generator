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
from badge_backend.services.headers import map_headers, SYNONYMS, LABELS  # noqa: F401
from badge_backend.api import MissingPhotosError  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = _api.default_db_path(ROOT)   # README: <project_dir>/project.db
ELEMENT_TYPES = ("text", "field", "photo", "image", "rect", "line", "qr", "barcode")   # 'line' — по решению Архитектора (миграция Backend)
SIDES = ("front", "back")


def pil_to_qimage(img):
    """PIL.Image (результат рендера Backend) -> QImage. Только конвертация, без рисования."""
    from PyQt6.QtGui import QImage
    img = img.convert("RGB")
    data = img.tobytes("raw", "RGB")
    return QImage(data, img.width, img.height, 3 * img.width, QImage.Format.Format_RGB888).copy()


class BackendAPI:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH, base_dir: str | Path | None = None):
        self.con = None
        self.open_db(db_path, base_dir)

    # --- БД ---
    def open_db(self, path, base_dir=None):
        if self.con is not None:
            self.con.close()
        self.db_path = path if str(path) == ":memory:" else Path(path)
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
    def upsert_field(self, name, label, sort_order=0): return _api.upsert_field(self.con, name, label, sort_order)
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
    def create_element(self, **kw): return _api.create_element(self.con, **kw)
    def update_element(self, eid, **changes): return _api.update_element(self.con, eid, **changes)
    def delete_element(self, eid): return _api.delete_element(self.con, eid)
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
    def missing_photos(self, ids=None): return _api.missing_photos(self.con, ids, self.base_dir)
    def snapshot(self, ids=None, sides=SIDES): return _api.snapshot(self.con, ids, tuple(sides))


# --- выполнение по snapshot: без соединения, безопасно в рабочем потоке ---
def export_png_from_snapshot(snap, out_dir, base_dir, progress=None, allow_missing_photo=False):
    return _api.export_png_from_snapshot(snap, out_dir, base_dir, progress=progress, allow_missing_photo=allow_missing_photo)


def export_pdf_from_snapshot(snap, out_path, base_dir, progress=None, allow_missing_photo=False):
    return _api.export_pdf_from_snapshot(snap, out_path, base_dir, progress=progress, allow_missing_photo=allow_missing_photo)


def print_snapshot(snap, printer, base_dir, progress=None, allow_missing_photo=False):
    return _api.print_snapshot(snap, printer, base_dir, progress=progress, allow_missing_photo=allow_missing_photo)
