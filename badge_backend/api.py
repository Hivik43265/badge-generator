"""Фасад backend для Frontend. Все функции принимают открытое соединение con (db.connect).

Координаты элементов — целые px холста 1011×638. Данные записей — только в persons.fields_json.
"""
from __future__ import annotations
import json
from .db import connect, DEFAULT_DB_PATH, default_db_path, get_schema_version  # noqa: F401  (реэкспорт)
from .photo_config import PhotoConfig, normalize, DEFAULT as PHOTO_CONFIG_DEFAULT  # noqa
from .render import render_card, render_card_db, render_preview  # noqa
from .services.importer import import_file  # noqa
from .services.exporter import (export_png, export_pdf, mark_printed, set_print_mark, snapshot,  # noqa
    export_png_from_snapshot, export_pdf_from_snapshot, missing_photos, MissingPhotosError)
from .services.headers import map_headers  # noqa
from .services.print_service import print_cards, print_snapshot  # noqa  (PyQt6 импортируется лениво)

_EL_COLS = ("type", "x", "y", "w", "h", "field_name", "static_value", "style_json", "side", "z_order")

def _row(r):
    if r is None: return None
    d = dict(r)
    for k in ("fields_json", "style_json"):
        if k in d: d[k.replace("_json", "") if k == "fields_json" else "style"] = json.loads(d[k] or "{}")
    return d

# ---------- persons ----------
def list_persons(con, only_marked: bool = False) -> list[dict]:
    """Список записей; в каждой есть 'fields' (dict из fields_json) и 'printed_at' (ISO 8601 со смещением или None)."""
    q = "SELECT * FROM persons" + (" WHERE print_mark=1" if only_marked else "") + " ORDER BY id"
    return [_row(r) for r in con.execute(q)]

def get_person(con, person_id: int) -> dict | None:
    return _row(con.execute("SELECT * FROM persons WHERE id=?", (person_id,)).fetchone())

def create_person(con, fields: dict, photo_path: str | None = None, photo_config: str | None = None,
                  print_mark: int = 0) -> int:
    """Создать запись, вернуть id. photo_config нормализуется (невалидный → default + warning)."""
    with con:
        return con.execute("INSERT INTO persons(fields_json, photo_path, photo_config, print_mark) VALUES (?,?,?,?)",
                           (json.dumps(fields or {}, ensure_ascii=False), photo_path,
                            normalize(photo_config), int(bool(print_mark)))).lastrowid

def update_person(con, person_id: int, fields: dict | None = None, photo_path=..., print_mark=None,
                  merge: bool = True) -> bool:
    """Обновить запись. fields сливаются с текущими (merge=True) или заменяют их."""
    p = get_person(con, person_id)
    if not p: return False
    sets, args = [], []
    if fields is not None:
        sets.append("fields_json=?"); args.append(json.dumps({**p["fields"], **fields} if merge else fields, ensure_ascii=False))
    if photo_path is not ...: sets.append("photo_path=?"); args.append(photo_path)
    if print_mark is not None: sets.append("print_mark=?"); args.append(int(bool(print_mark)))
    if not sets: return True
    with con: con.execute(f"UPDATE persons SET {','.join(sets)}, updated_at=datetime('now') WHERE id=?", (*args, person_id))
    return True

def delete_person(con, person_id: int) -> bool:
    with con: return con.execute("DELETE FROM persons WHERE id=?", (person_id,)).rowcount > 0

def update_photo_config(con, person_id: int, config: str | PhotoConfig) -> str:
    """Сохранить photo_config (строка или PhotoConfig). Возвращает записанную нормализованную строку."""
    s = config.dump() if isinstance(config, PhotoConfig) else normalize(config)
    with con: con.execute("UPDATE persons SET photo_config=?, updated_at=datetime('now') WHERE id=?", (s, person_id))
    return s

def list_fields(con) -> list[dict]:
    """Метаданные колонок (name, label, sort_order) для таблицы и редактора шаблона."""
    return [dict(r) for r in con.execute("SELECT * FROM person_fields ORDER BY sort_order, name")]

def upsert_field(con, name: str, label: str, sort_order: int = 0) -> None:
    with con: con.execute("INSERT INTO person_fields VALUES (?,?,?) ON CONFLICT(name) DO UPDATE SET "
                          "label=excluded.label, sort_order=excluded.sort_order", (name, label, sort_order))

# ---------- template_elements ----------
def list_elements(con, side: str | None = None) -> list[dict]:
    """Элементы шаблона по z_order; 'style' — dict из style_json."""
    q = "SELECT * FROM template_elements" + (" WHERE side=?" if side else "") + " ORDER BY side, z_order, id"
    return [_row(r) for r in con.execute(q, (side,) if side else ())]

def _el_vals(d):
    d = dict(d)
    if "style" in d and "style_json" not in d: d["style_json"] = d.pop("style")
    if isinstance(d.get("style_json"), dict): d["style_json"] = json.dumps(d["style_json"], ensure_ascii=False)
    for k in ("x", "y", "w", "h"):
        if k in d: d[k] = int(round(d[k]))
    return {k: v for k, v in d.items() if k in _EL_COLS}

def create_element(con, type: str, x: int, y: int, w: int, h: int, side: str = "front", z_order: int = 0,
                   field_name: str | None = None, static_value: str | None = None, style: dict | None = None) -> int:
    """Добавить элемент (type: text|field|photo|image|rect|qr|barcode|line; у line w,h — вектор, может быть ≤0, но не (0,0)). Нарушение CHECK → sqlite3.IntegrityError."""
    v = _el_vals(dict(type=type, x=x, y=y, w=w, h=h, side=side, z_order=z_order, field_name=field_name,
                      static_value=static_value, style_json=style or {}))
    with con:
        return con.execute(f"INSERT INTO template_elements({','.join(v)}) VALUES ({','.join('?'*len(v))})",
                           tuple(v.values())).lastrowid

def update_element(con, element_id: int, **changes) -> bool:
    """Изменить поля элемента (x, y, w, h, style={...}, z_order, ...)."""
    v = _el_vals(changes)
    if not v: return True
    with con:
        return con.execute(f"UPDATE template_elements SET {','.join(k+'=?' for k in v)} WHERE id=?",
                           (*v.values(), element_id)).rowcount > 0

def delete_element(con, element_id: int) -> bool:
    with con: return con.execute("DELETE FROM template_elements WHERE id=?", (element_id,)).rowcount > 0

def set_background(con, side: str, color: str = "#FFFFFF", image_path: str | None = None) -> None:
    """Фон стороны: цвет и/или картинка (растягивается cover)."""
    with con: con.execute("INSERT INTO template_backgrounds(side,image_path,color) VALUES (?,?,?) ON CONFLICT(side) "
                          "DO UPDATE SET image_path=excluded.image_path, color=excluded.color", (side, image_path, color))

def get_background(con, side: str) -> dict | None:
    r = con.execute("SELECT * FROM template_backgrounds WHERE side=?", (side,)).fetchone()
    return dict(r) if r else None
