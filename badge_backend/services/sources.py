"""Этап 13: источники импорта (.xlsx/.xlsm, .xls, .csv/.txt, .db) и импорт выбранного листа.

open_source(path) -> list[Sheet]
read_rows(sheet, header=True, limit=None) -> (columns, rows)
auto_match(columns, mapping=None) -> list[str|None]            (headers.map_headers)
import_rows(con, sheet, mapping=None, *, header=True, ...) -> ImportReport   (ядро — importer.import_records)
save_mapping(path, mapping) / load_mapping(path)

.db: проектная БД (есть persons и person_fields) любой user_version копируется во временный файл
(backup API из соединения mode=ro), копия мигрируется до LATEST; исходный файл не меняется.
Произвольная SQLite — каждая таблица отдельный лист, чтение только через URI mode=ro.
"""
from __future__ import annotations
import json, sqlite3, tempfile, warnings
from dataclasses import dataclass, field
from pathlib import Path
from .headers import map_headers
from .importer import read_table, xls_rows, parse_rows, import_records, ImportReport, _cell

XLSX = (".xlsx", ".xlsm"); CSV = (".csv", ".txt")
PROJECT_COLS = ["photo_path", "photo_config", "print_mark", "printed_at"]   # служебные колонки листа «persons»

@dataclass
class Sheet:
    """Лист/таблица источника. kind: 'xlsx' | 'xls' | 'csv' | 'project' | 'sqlite'."""
    path: Path
    name: str
    kind: str
    index: int = 0
    work_path: Path | None = None          # для 'project' — мигрированная временная копия
    schema_version: int | None = None      # для 'project' — версия ИСХОДНОЙ БД
    meta: dict = field(default_factory=dict)
    def close(self):
        """Удалить временную мигрированную копию ('project'); повторный вызов безопасен."""
        if self.work_path is not None:
            try: Path(self.work_path).unlink(missing_ok=True)
            except OSError: pass
            self.work_path = None
    def as_dict(self):
        return {"path": str(self.path), "name": self.name, "kind": self.kind, "index": self.index,
                "schema_version": self.schema_version}

def _ro(path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{Path(path).resolve().as_posix()}?mode=ro", uri=True)

def _tables(con):
    return [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view') "
                                      "AND name NOT LIKE 'sqlite_%' ORDER BY name")]

def open_source(path) -> list[Sheet]:
    """Список листов/таблиц источника. Неизвестный формат → ValueError; не SQLite (.db) → ValueError."""
    p = Path(path); suf = p.suffix.lower()
    if not p.is_file(): raise FileNotFoundError(p)
    if suf in XLSX:
        from openpyxl import load_workbook
        wb = load_workbook(p, read_only=True); names = wb.sheetnames; wb.close()
        return [Sheet(p, n, "xlsx", i) for i, n in enumerate(names)]
    if suf == ".xls":
        import xlrd
        wb = xlrd.open_workbook(str(p), on_demand=True); names = wb.sheet_names(); wb.release_resources()
        return [Sheet(p, n, "xls", i) for i, n in enumerate(names)]
    if suf in CSV:
        return [Sheet(p, p.stem, "csv")]
    if suf in (".db", ".sqlite", ".sqlite3"):
        src = _ro(p)
        try:
            try: tabs = _tables(src)
            except sqlite3.DatabaseError as e: raise ValueError(f"не БД SQLite: {e}") from e
            if {"persons", "person_fields"} <= set(tabs):
                from .. import db
                ver = db.get_schema_version(src)
                fd, tmp = tempfile.mkstemp(prefix="bg_import_", suffix=".db"); import os; os.close(fd)
                dst = sqlite3.connect(tmp)
                try: src.backup(dst); db.migrate(dst)
                finally: dst.close()
                return [Sheet(p, "persons", "project", 0, Path(tmp), ver)]
            return [Sheet(p, t, "sqlite", i) for i, t in enumerate(tabs)]
        finally:
            src.close()
    raise ValueError(f"неподдерживаемый формат: {suf}")

def _project_rows(sheet):
    if sheet.work_path is None: raise ValueError("лист закрыт (Sheet.close)")
    con = sqlite3.connect(str(sheet.work_path)); con.row_factory = sqlite3.Row
    try:
        fields = [dict(r) for r in con.execute("SELECT * FROM person_fields ORDER BY sort_order, name")]
        names = [f["name"] for f in fields]
        rows = []
        for r in con.execute("SELECT * FROM persons ORDER BY id"):
            fj = json.loads(r["fields_json"] or "{}")
            extra = [k for k in fj if k not in names]
            for k in extra: names.append(k)
            rows.append((fj, r))
        cols = names + PROJECT_COLS
        out = [[fj.get(n, "") for n in names] + [r["photo_path"], r["photo_config"], r["print_mark"], r["printed_at"]]
               for fj, r in rows]
        sheet.meta["fields"] = {f["name"]: f for f in fields}
        return cols, out
    finally:
        con.close()

def _raw(sheet):
    """Все строки листа без разбора заголовка."""
    if sheet.kind == "xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(sheet.path, read_only=True, data_only=True)
        try: return [list(r) for r in wb.worksheets[sheet.index].iter_rows(values_only=True)]
        finally: wb.close()
    if sheet.kind == "xls":
        import xlrd
        wb = xlrd.open_workbook(str(sheet.path))
        try: return xls_rows(wb, wb.sheet_by_index(sheet.index))
        finally: wb.release_resources()
    if sheet.kind == "csv":
        h, rows = read_table(sheet.path); return [h, *rows]
    if sheet.kind == "sqlite":
        con = _ro(sheet.path)
        try:
            cur = con.execute('SELECT * FROM "' + sheet.name.replace('"', '""') + '"')   # имя — из sqlite_master
            return [[d[0] for d in cur.description], *[list(r) for r in cur]]
        finally: con.close()
    raise ValueError(f"неизвестный kind: {sheet.kind}")

def read_rows(sheet: Sheet, header: bool = True, limit: int | None = None) -> tuple[list[str], list[list[str]]]:
    """Прочитать лист → (columns, rows). Значения — строки (как при импорте: strip, int без .0, даты ISO).
    header=True — первая непустая строка = заголовки; False — колонки 'Колонка 1..N', все строки — данные.
    limit — максимум строк данных (None — все). Для 'project' и 'sqlite' заголовки всегда из схемы."""
    if sheet.kind == "project":
        cols, rows = _project_rows(sheet)
    else:
        raw = _raw(sheet)
        if sheet.kind != "sqlite":
            while raw and all(_cell(c) == "" for c in raw[0]): raw.pop(0)
        if header or sheet.kind == "sqlite":
            cols, rows = ([_cell(c) for c in raw[0]] if raw else []), raw[1:]
        else:
            n = max((len(r) for r in raw), default=0)
            cols, rows = [f"Колонка {i + 1}" for i in range(n)], raw
    rows = [[_cell(c) for c in r] for r in (rows if limit is None else rows[:max(0, int(limit))])]
    return cols, rows

def auto_match(columns, mapping: dict | None = None) -> list:
    """Ключ поля для каждой колонки (None — пропустить). Единый источник правил — headers.map_headers."""
    return map_headers(columns, mapping)

def _xlsx_images(sheet, photo_dir, header_offset):
    """Встроенные картинки xlsx → {номер_строки_Excel: имя_файла в photo_dir}.
    Берётся левый-верхний угол якоря (OneCell/TwoCell); AbsoluteAnchor не привязан к ячейке — пропускается."""
    from openpyxl import load_workbook
    wb = load_workbook(sheet.path)          # не read_only: картинки доступны только так
    out, skipped = {}, 0
    try:
        ws = wb.worksheets[sheet.index]
        for k, img in enumerate(getattr(ws, "_images", [])):
            fr = getattr(getattr(img, "anchor", None), "_from", None)
            if fr is None: skipped += 1; continue
            row = fr.row + 1
            data = img._data()
            ext = (getattr(img, "format", None) or "png").lower().replace("jpeg", "jpg")
            name = f"{Path(sheet.path).stem}_{sheet.index}_r{row}_c{fr.col + 1}.{ext}"
            Path(photo_dir).mkdir(parents=True, exist_ok=True)
            (Path(photo_dir) / name).write_bytes(data)
            out.setdefault(row, name)
    finally:
        wb.close()
    return out, skipped

def import_rows(con, sheet: Sheet, mapping: dict | None = None, *, header: bool = True, photo_dir=None,
                validate: bool = True, labels: dict | None = None, require_photo: bool = False,
                progress=None, cancel=None, extract_images: bool = True) -> ImportReport:
    """Импортировать лист в persons (одна транзакция; ядро — importer.import_records, как у import_file).

    mapping        формат headers.map_headers ({заголовок: 'field'|None}, {field: [синонимы]}).
    photo_dir      база для photo_path; колонка с путём (photo_path/«Фото»…) используется как есть.
    extract_images xlsx: встроенные картинки сохраняются в photo_dir по якорной ячейке и становятся
                   photo_path строки якоря (если у строки нет пути). Нет photo_dir → картинки пропускаются + warning.
    progress       callable(done, total); вернул False → отмена.
    cancel         callable() → True или threading.Event — отмена; транзакция откатывается, report.cancelled=True.
    project (.db)  поля, photo_path/photo_config, print_mark/printed_at; label и default_value полей
                   переносятся, если у текущего проекта их нет. Исходный файл не меняется."""
    cols, rows = read_rows(sheet, header=header)
    extra = None
    if sheet.kind == "project":
        flds = sheet.meta.get("fields", {})
        mp = {c: c for c in cols if c not in ("print_mark", "printed_at")}
        mp.update({"print_mark": None, "printed_at": None}); mp.update(mapping or {})
        labels = {**{k: f["label"] for k, f in flds.items()}, **(labels or {})}
        recs, labs = parse_rows(cols, rows, mp, labels)
        pm, pa = cols.index("print_mark"), cols.index("printed_at")
        nonempty = [r for r in rows if any(v != "" for v in r)]
        extra = {i: {"print_mark": r[pm] == "1", "printed_at": r[pa] or None} for i, r in enumerate(nonempty)}
        exist = {r[0] for r in con.execute("SELECT name FROM person_fields")}
        lab_new = {k: v for k, v in labels.items() if k not in exist}
        rep = import_records(con, recs, labs, photo_dir, validate, labels=lab_new, require_photo=require_photo,
                             progress=progress, cancel=cancel, extra=extra)
        if not rep.cancelled:
            with con:
                for k, f in flds.items():
                    if f.get("default_value") not in (None, ""):
                        con.execute("UPDATE person_fields SET default_value=? WHERE name=? AND default_value IS NULL",
                                    (f["default_value"], k))
        return rep
    recs, labs = parse_rows(cols, rows, mapping, labels)
    if sheet.kind == "xlsx" and extract_images and header:
        if photo_dir is None:
            from openpyxl import load_workbook
            wb = load_workbook(sheet.path); n = len(getattr(wb.worksheets[sheet.index], "_images", [])); wb.close()
            if n: warnings.warn(f"в листе {n} встроенных картинок; без photo_dir они не извлекаются", RuntimeWarning)
        else:
            imgs, _ = _xlsx_images(sheet, photo_dir, 1)
            # номер строки Excel: строка данных r['_row'] совпадает, если заголовок — первая строка листа
            raw_first = next((i for i, r in enumerate(_raw(sheet)) if any(_cell(c) != "" for c in r)), 0)
            for r in recs:
                xl_row = r["_row"] + raw_first
                if not r.get("photo_path") and xl_row in imgs: r["photo_path"] = imgs[xl_row]
    return import_records(con, recs, labs, photo_dir, validate, labels=labels, require_photo=require_photo,
                          progress=progress, cancel=cancel)

MAPPING_FORMAT = "badge-generator/mapping"

def save_mapping(path, mapping: dict, *, columns=None) -> Path:
    """Сохранить mapping в JSON (UTF-8): {"format", "version": 1, "mapping": {...}, "columns": [...]}. → Path."""
    p = Path(path)
    for k, v in mapping.items():
        if not isinstance(k, str) or not (v is None or isinstance(v, (str, list, tuple))):
            raise ValueError(f"неверная запись mapping: {k!r}: {v!r}")
    data = {"format": MAPPING_FORMAT, "version": 1,
            "mapping": {k: (list(v) if isinstance(v, tuple) else v) for k, v in mapping.items()}}
    if columns is not None: data["columns"] = list(columns)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p

def load_mapping(path) -> dict:
    """Прочитать mapping, сохранённый save_mapping. Чужой/битый файл → ValueError."""
    try: data = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as e: raise ValueError(f"не JSON: {e}") from e
    if not isinstance(data, dict) or data.get("format") != MAPPING_FORMAT or not isinstance(data.get("mapping"), dict):
        raise ValueError("файл не является mapping Badge Generator")
    if data.get("version") != 1: raise ValueError(f"неподдерживаемая версия mapping: {data.get('version')}")
    return data["mapping"]
