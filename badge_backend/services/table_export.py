"""Этап 13: экспорт записей в таблицу (.xlsx, .xls, .csv) или в новую проектную БД (.db).

export_persons(con, path, format=None, ids=None, *, photo_dir=None, csv_encoding="utf-8-sig") -> dict
Заголовки таблиц — label полей (person_fields), затем «Фото» и «Настройки фото», чтобы файл
импортировался обратно через headers.map_headers (фото/настройки распознаются синонимами).
"""
from __future__ import annotations
import csv, json, shutil, sqlite3
from pathlib import Path

FORMATS = ("xlsx", "xls", "csv", "db")
XLS_MAX_ROWS = 65535            # строк данных (+1 строка заголовка = 65536 — предел формата .xls)
PHOTO_HEADERS = ("Фото", "Настройки фото")

def _q(con, sql, args=()):
    c = con.cursor(); c.row_factory = sqlite3.Row    # не меняем row_factory соединения вызывающего
    return c.execute(sql, args)

def _persons(con, ids):
    q = "SELECT * FROM persons"
    if ids is None: return list(_q(con, q + " ORDER BY id"))
    by = {r["id"]: r for r in _q(con, q)}
    return [by[int(i)] for i in ids if int(i) in by]

def _fields(con):
    return [dict(r) for r in _q(con, "SELECT * FROM person_fields ORDER BY sort_order, name")]

def table_rows(con, ids=None):
    """→ (headers, rows) для табличных форматов. Ключи fields_json вне person_fields — отдельными колонками."""
    ps = _persons(con, ids); flds = _fields(con)
    keys = [f["name"] for f in flds]; heads = [f["label"] or f["name"] for f in flds]
    data = []
    for r in ps:
        fj = json.loads(r["fields_json"] or "{}")
        for k in fj:
            if k not in keys: keys.append(k); heads.append(k)
        data.append((fj, r))
    rows = [[("" if fj.get(k) is None else str(fj.get(k))) for k in keys] + [r["photo_path"] or "", r["photo_config"] or ""]
            for fj, r in data]
    return heads + list(PHOTO_HEADERS), rows

def _fmt(path, format):
    f = (format or Path(path).suffix.lstrip(".")).lower()
    if f == "sqlite": f = "db"
    if f not in FORMATS: raise ValueError(f"формат: {FORMATS}, получено {f!r}")
    return f

def _copy_file(src_rel, base_dir, dst_dir, used, warn):
    if not src_rel: return src_rel, False
    s = Path(src_rel)
    if not s.is_absolute() and base_dir: s = Path(base_dir) / s
    if not s.is_file(): warn.append(f"файл не найден: {src_rel}"); return src_rel, False
    name = s.name; i = 1
    while name in used and used[name] != s.resolve(): name = f"{s.stem}_{i}{s.suffix}"; i += 1
    used[name] = s.resolve(); dst_dir.mkdir(parents=True, exist_ok=True)
    if not (dst_dir / name).exists(): shutil.copy2(s, dst_dir / name)
    return name, True

def _export_db(con, path, ids, photo_dir):
    from .. import db
    out = Path(path)
    if out.exists(): raise FileExistsError(out)
    pdir = out.with_name(out.stem + "_photos")
    warn, used, copied = [], {}, 0
    ps = _persons(con, ids)
    new = db.connect(out)
    try:
        with new:
            for f in _fields(con):
                new.execute("INSERT INTO person_fields(name,label,sort_order,default_value) VALUES (?,?,?,?)",
                            (f["name"], f["label"], f["sort_order"], f.get("default_value")))
            for r in ps:
                pp, ok = _copy_file(r["photo_path"], photo_dir, pdir, used, warn); copied += ok
                new.execute("INSERT INTO persons(fields_json,photo_path,photo_config,print_mark,printed_at,created_at,updated_at) "
                            "VALUES (?,?,?,?,?,?,?)", (r["fields_json"], pp, r["photo_config"], r["print_mark"],
                                                       r["printed_at"], r["created_at"], r["updated_at"]))
            cols = "id,type,x,y,w,h,field_name,static_value,style_json,side,z_order"
            for e in _q(con, f"SELECT {cols} FROM template_elements ORDER BY id"):
                e = dict(e)
                if e["type"] == "image": e["static_value"], ok = _copy_file(e["static_value"], photo_dir, pdir, used, warn); copied += ok
                new.execute(f"INSERT INTO template_elements({cols}) VALUES ({','.join('?' * 11)})", tuple(e.values()))
            for b in _q(con, "SELECT side,image_path,color FROM template_backgrounds"):
                ip, ok = _copy_file(b["image_path"], photo_dir, pdir, used, warn); copied += ok
                new.execute("INSERT INTO template_backgrounds(side,image_path,color) VALUES (?,?,?)", (b["side"], ip, b["color"]))
    finally:
        new.close()
    return {"path": out, "format": "db", "rows": len(ps), "photo_dir": pdir if copied else None,
            "files_copied": copied, "warnings": warn}

def export_persons(con, path, format: str | None = None, ids=None, *, photo_dir=None,
                   csv_encoding: str = "utf-8-sig") -> dict:
    """Экспорт записей. format: 'xlsx'|'xls'|'csv'|'db' (None — по расширению path).
    ids None — все записи (по id), иначе — в заданном порядке (несуществующие пропускаются).
    csv: разделитель ';', csv_encoding 'utf-8-sig' (по умолчанию) или 'cp1251'.
    xls: больше 65535 строк данных → ValueError (файл не создаётся).
    db: новая проектная БД (LATEST) с выбранными записями, полями (label, default_value), элементами и фонами;
        фото и картинки шаблона копируются в '<имя>_photos/' рядом (photo_dir — база относительных путей),
        пути в новой БД — имена файлов в этой папке. Существующий path → FileExistsError.
    → {"path": Path, "format", "rows": int, "warnings": [...], ...}."""
    f = _fmt(path, format); p = Path(path)
    if f == "db": return _export_db(con, p, ids, photo_dir)
    heads, rows = table_rows(con, ids)
    if f == "xls" and len(rows) > XLS_MAX_ROWS:
        raise ValueError(f"Слишком много записей для формата .xls: выбрано {len(rows)}, максимум {XLS_MAX_ROWS}. "
                         f"Выберите формат .xlsx (Excel 2007+) — в нём ограничения нет.")
    p.parent.mkdir(parents=True, exist_ok=True)
    if f == "csv":
        if csv_encoding.lower().replace("_", "-") not in ("utf-8-sig", "utf-8", "cp1251"):
            raise ValueError("csv_encoding: 'utf-8-sig' | 'utf-8' | 'cp1251'")
        with open(p, "w", newline="", encoding=csv_encoding) as fh:
            w = csv.writer(fh, delimiter=";"); w.writerow(heads); w.writerows(rows)
    elif f == "xlsx":
        from openpyxl import Workbook
        wb = Workbook(); ws = wb.active; ws.title = "Записи"
        ws.append(heads)
        for r in rows: ws.append(r)
        from openpyxl.styles import Font
        for c in ws[1]: c.font = Font(bold=True)
        wb.save(p)
    else:
        import xlwt
        wb = xlwt.Workbook(encoding="utf-8"); ws = wb.add_sheet("Записи")
        bold = xlwt.easyxf("font: bold on")
        for j, h in enumerate(heads): ws.write(0, j, h, bold)
        for i, r in enumerate(rows, 1):
            for j, v in enumerate(r): ws.write(i, j, v)
        wb.save(str(p))
    return {"path": p, "format": f, "rows": len(rows), "warnings": []}
