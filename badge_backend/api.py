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
    """Метаданные колонок (name, label, sort_order, default_value) для таблицы и редактора шаблона."""
    return [dict(r) for r in con.execute("SELECT * FROM person_fields ORDER BY sort_order, name")]

def upsert_field(con, name: str, label: str, sort_order: int = 0, default_value: str | None = ...) -> None:
    """Создать/обновить поле. default_value не передан (...) — не менять; None/'' — сбросить."""
    if default_value is ...:
        with con: con.execute("INSERT INTO person_fields(name,label,sort_order) VALUES (?,?,?) ON CONFLICT(name) DO UPDATE SET "
                              "label=excluded.label, sort_order=excluded.sort_order", (name, label, sort_order))
    else:
        dv = None if default_value in (None, "") else str(default_value)
        with con: con.execute("INSERT INTO person_fields(name,label,sort_order,default_value) VALUES (?,?,?,?) ON CONFLICT(name) "
                              "DO UPDATE SET label=excluded.label, sort_order=excluded.sort_order, default_value=excluded.default_value",
                              (name, label, sort_order, dv))

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

# ---------- этап 12 (сигнатуры — reports/stage-12-actions.md §3) ----------
from pathlib import Path as _Path
import sqlite3 as _sqlite3
from . import db as _db

def _field_names(con) -> set[str]:
    return {r[0] for r in con.execute("SELECT name FROM person_fields")}

def _need_field(con, name):
    if name not in _field_names(con): raise ValueError(f"неизвестное поле: {name!r}")

def _ids_list(ids):
    return [int(i) for i in ids]

# --- поля: default_value ---
def set_field_default(con, name: str, default_value: str | None) -> None:
    """person_fields.default_value; подставляется в рендер, если у записи поле пустое/None. None/'' — сбросить."""
    _need_field(con, name)
    with con: con.execute("UPDATE person_fields SET default_value=? WHERE name=?",
                          (None if default_value in (None, "") else str(default_value), name))

def delete_field(con, name: str, *, unlink: bool = True) -> bool:
    """Удалить поле из person_fields (данные в fields_json не трогаются). Привязанные элементы:
    unlink=True — отвязываются (unlink_field); unlink=False — ValueError, если поле используется. Нет поля → False."""
    if name not in _field_names(con): return False
    linked = list_field_links(con).get(name, [])
    if linked and not unlink: raise ValueError(f"поле {name!r} используется элементами {[e['element_id'] for e in linked]}")
    with con:
        for e in linked: _unlink(con, e["element_id"], None)
        con.execute("DELETE FROM person_fields WHERE name=?", (name,))
    return True

# --- связь поля и объектов шаблона ---
def list_field_links(con) -> dict[str, list[dict]]:
    """field_name → [{'element_id', 'id' (= element_id), 'type', 'side', 'label'}]; label — static_value или ''."""
    out: dict[str, list[dict]] = {}
    for r in con.execute("SELECT id, type, side, field_name, static_value FROM template_elements "
                         "WHERE field_name IS NOT NULL ORDER BY field_name, id"):
        out.setdefault(r[3], []).append({"element_id": r[0], "id": r[0], "type": r[1], "side": r[2], "label": r[4] or ""})
    return out

_LINKABLE = ("field", "barcode", "qr")

def link_field(con, element_id: int, field_name: str) -> bool:
    """Привязать элемент типа field|barcode|qr к полю (поле должно существовать, иначе ValueError;
    другой тип → ValueError). Нет элемента → False."""
    _need_field(con, field_name)
    r = con.execute("SELECT type FROM template_elements WHERE id=?", (element_id,)).fetchone()
    if r is None: return False
    if r[0] not in _LINKABLE: raise ValueError(f"тип {r[0]!r} нельзя привязать к полю (только {_LINKABLE})")
    with con: con.execute("UPDATE template_elements SET field_name=? WHERE id=?", (field_name, element_id))
    return True

def _unlink(con, element_id, static_value):
    sv = "COALESCE(?, static_value)"
    return con.execute(f"UPDATE template_elements SET field_name=NULL, static_value={sv}, "
                       "type=CASE WHEN type='field' THEN 'text' ELSE type END WHERE id=?",
                       (static_value, element_id)).rowcount > 0

def unlink_field(con, element_id: int, static_value: str | None = None) -> bool:
    """Отвязать: field → text, barcode/qr остаются; static_value (если задан) записывается, иначе прежний сохраняется.
    Нет элемента → False."""
    with con: return _unlink(con, element_id, static_value)

# --- карты ---
def delete_persons(con, ids) -> int:
    """Пакетное удаление одной транзакцией. → число удалённых."""
    ids = _ids_list(ids)
    with con: return sum(con.execute("DELETE FROM persons WHERE id=?", (i,)).rowcount for i in ids)

def clear_printed(con, ids) -> int:
    """Снять статус «напечатано» (printed_at=NULL); print_mark не трогает. → число изменённых."""
    ids = _ids_list(ids)
    with con: return sum(con.execute("UPDATE persons SET printed_at=NULL, updated_at=datetime('now') "
                                     "WHERE id=? AND printed_at IS NOT NULL", (i,)).rowcount for i in ids)

# --- query_persons ---
QUERY_OPS = ("eq", "ne", "contains", "startswith", "empty", "not_empty")
_SYS_FIELDS = {"id": "CAST(id AS TEXT)", "print_mark": "CAST(print_mark AS TEXT)", "printed_at": "COALESCE(printed_at, '')"}

def _fold(s): return None if s is None else str(s).casefold()

def _term(t, names, args):
    if not isinstance(t, dict): raise ValueError(f"условие должно быть dict: {t!r}")
    if "terms" in t:
        j = t.get("join", "and")
        if j not in ("and", "or"): raise ValueError(f"join: 'and'|'or', получено {j!r}")
        parts = [_term(x, names, args) for x in t["terms"]]
        return "(" + f" {j.upper()} ".join(parts) + ")" if parts else "1"
    f, op, v = t.get("field"), t.get("op"), t.get("value")
    if op not in QUERY_OPS: raise ValueError(f"неизвестное условие {op!r}; допустимо {QUERY_OPS}")
    if f in _SYS_FIELDS: col = _SYS_FIELDS[f]
    elif f in names:
        col = "COALESCE(CAST(json_extract(fields_json, ?) AS TEXT), '')"; args.append('$."' + f + '"')
    else: raise ValueError(f"неизвестное поле: {f!r}")
    if op == "empty": return f"TRIM({col}) = ''"
    if op == "not_empty": return f"TRIM({col}) <> ''"
    if v is None: raise ValueError(f"для {op!r} нужно value")
    args.append(_fold(v))
    return {"eq": f"_bg_fold({col}) = ?", "ne": f"_bg_fold({col}) <> ?",
            "contains": f"instr(_bg_fold({col}), ?) > 0",
            "startswith": f"_bg_starts(_bg_fold({col}), ?)"}[op]

def query_persons(con, where: dict | None = None, printed: bool | None = None,
                  only_marked: bool = False, order_by: str = "id") -> list[dict]:
    """Отбор записей по выражению-данным (SQL от вызывающего не принимается, всё параметризовано).

    where     None | {"join": "and"|"or", "terms": [Condition | Where, ...]} (вложенность = скобки);
              Condition = {"field": имя из person_fields | "id" | "print_mark" | "printed_at",
                           "op": "eq"|"ne"|"contains"|"startswith"|"empty"|"not_empty", "value": str|None}.
              Сравнение строковое, без учёта регистра (в т.ч. кириллица); empty/not_empty — value не нужен
              (пробелы считаются пустым).
    printed   None — все; True — printed_at IS NOT NULL; False — printed_at IS NULL.
    only_marked  только print_mark=1.
    order_by  "id" | "printed_at" | "print_mark" | имя поля person_fields; префикс "-" — по убыванию.
    Ошибка формата (поле/op/join не из белого списка, нет value) → ValueError. Элементы — как list_persons.
    """
    con.create_function("_bg_fold", 1, _fold, deterministic=True)
    con.create_function("_bg_starts", 2, lambda a, b: int(str(a or "").startswith(b or "")), deterministic=True)
    names = _field_names(con); args: list = []; conds = []
    if where is not None:
        if isinstance(where, dict) and "terms" not in where: where = {"join": "and", "terms": [where]}
        conds.append(_term(where, names, args))
    if printed is not None: conds.append("printed_at IS NOT NULL" if printed else "printed_at IS NULL")
    if only_marked: conds.append("print_mark=1")
    desc = isinstance(order_by, str) and order_by.startswith("-"); ob = order_by[1:] if desc else order_by
    if ob in ("id", "printed_at", "print_mark"): oexpr = ob
    elif ob in names: oexpr = "_bg_fold(json_extract(fields_json, ?))"; args.append('$."' + ob + '"')
    else: raise ValueError(f"order_by: неизвестное поле {order_by!r}")
    q = "SELECT * FROM persons" + (" WHERE " + " AND ".join(conds) if conds else "") + \
        f" ORDER BY {oexpr} {'DESC' if desc else 'ASC'}, id"
    return [_row(r) for r in con.execute(q, args)]

# --- бэкап / сжатие / восстановление ---
def _db_file(con):
    f = con.execute("PRAGMA database_list").fetchone()[2]
    return _Path(f) if f else None

def backup_db(con, dest_path) -> _Path:
    """Копия БД через sqlite3 backup API (консистентно): пишется во временный файл рядом, затем атомарная замена.
    dest_path не может совпадать с открытой БД (ValueError). → Path копии."""
    import os
    dest = _Path(dest_path); src = _db_file(con)
    if src and src.resolve() == dest.resolve(): raise ValueError("dest_path совпадает с открытой БД")
    if con.in_transaction: con.commit()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    if tmp.exists(): tmp.unlink()
    b = _sqlite3.connect(str(tmp))
    try: con.backup(b)
    finally: b.close()
    os.replace(tmp, dest)
    return dest

def _size(con):
    return con.execute("PRAGMA page_count").fetchone()[0] * con.execute("PRAGMA page_size").fetchone()[0]

def vacuum_db(con) -> dict:
    """VACUUM открытой БД. → {"size_before": int, "size_after": int} (байты, page_count×page_size)."""
    if con.in_transaction: con.commit()
    before = _size(con); con.execute("VACUUM")
    return {"size_before": before, "size_after": _size(con)}

def compact_and_backup(con, backup_dir) -> dict:
    """backup_db в backup_dir (имя project-ГГГГММДД-ЧЧММСС.db) + PRAGMA integrity_check + VACUUM.
    → {"backup": Path, "size_before", "size_after", "integrity": "ok"}. integrity не ok → RuntimeError (VACUUM не делается)."""
    from datetime import datetime
    d = _Path(backup_dir); stem = (_db_file(con).stem if _db_file(con) else "project")
    dest = d / f"{stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    n = 1
    while dest.exists(): dest = d / f"{stem}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{n}.db"; n += 1
    backup_db(con, dest)
    integ = con.execute("PRAGMA integrity_check").fetchone()[0]
    if integ != "ok": raise RuntimeError(f"integrity_check: {integ}")
    return {"backup": dest, **vacuum_db(con), "integrity": integ}

def restore_db(target_path, backup_path) -> None:
    """Восстановить target_path из backup_path. Проверки бэкапа: integrity_check == 'ok',
    1 ≤ schema_version ≤ LATEST (иначе ValueError). Запись через backup API, затем migrate до LATEST.
    Соединения с target_path нужно закрыть до вызова и открыть заново после."""
    bp, tp = _Path(backup_path), _Path(target_path)
    if not bp.is_file(): raise FileNotFoundError(bp)
    if bp.resolve() == tp.resolve(): raise ValueError("backup_path совпадает с target_path")
    src = _sqlite3.connect(f"file:{bp.as_posix()}?mode=ro", uri=True)
    try:
        try: integ = src.execute("PRAGMA integrity_check").fetchone()[0]
        except _sqlite3.DatabaseError as e: raise ValueError(f"не БД SQLite: {e}") from e
        if integ != "ok": raise ValueError(f"integrity_check: {integ}")
        v = _db.get_schema_version(src)
        if not 1 <= v <= _db.LATEST: raise ValueError(f"schema_version {v} вне 1..{_db.LATEST}")
        tp.parent.mkdir(parents=True, exist_ok=True)
        dst = _sqlite3.connect(str(tp))
        try: src.backup(dst); _db.migrate(dst)
        finally: dst.close()
    finally:
        src.close()
