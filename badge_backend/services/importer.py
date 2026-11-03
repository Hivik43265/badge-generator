"""Импорт Excel/CSV в persons.

import_file(con, path, mapping=None, photo_dir=None) -> ImportReport
 - .xlsx/.xlsm через openpyxl (первый лист), .csv с автоопределением кодировки
   (utf-8-sig → cp1251) и разделителя (; , \\t |).
 - заголовки → ключи через services.headers.map_headers; label = исходный заголовок → person_fields.
 - колонка фото → persons.photo_path (относительно photo_dir; хранится относительный путь),
   photo_config → persons.photo_config (нормализуется; невалидный → default + warning).
 - пустые строки пропускаются (не считаются skipped).
 - после парсинга записи передаются в data_tools.validate_import (мягкий импорт, см. _validate).
   Строки с ошибками валидации не добавляются (skipped) и попадают в errors.
"""
from __future__ import annotations
import csv, io, json, logging, warnings
from dataclasses import dataclass, field
from pathlib import Path
from .headers import map_headers, split_fio, column_labels
from ..photo_config import normalize, DEFAULT
log = logging.getLogger(__name__)
FALLBACK_VALIDATOR = "builtin-fallback"  # report.validator, если data_tools недоступен

@dataclass
class ImportReport:
    added: int = 0
    skipped: int = 0
    errors: list = field(default_factory=list)   # [{'row', 'field', 'code', 'details'}]
    ids: list = field(default_factory=list)
    validator: str = ""
    warnings: list = field(default_factory=list)  # [{'row','field','code','details'}], напр. PHOTO_MISSING
    cancelled: bool = False
    def as_dict(self): return {"added": self.added, "skipped": self.skipped, "errors": self.errors,
                               "warnings": self.warnings, "ids": self.ids, "validator": self.validator,
                               "cancelled": self.cancelled}

def _cell(v):
    """Значение ячейки → строка без потерь: только strip и \r\n→\n (внутренние пробелы/переносы сохраняются).
    float-целые → int ('123', не '123.0'); дата без времени → 'YYYY-MM-DD'."""
    import datetime as _dt
    if v is None: return ""
    if isinstance(v, bool): return "1" if v else "0"
    if isinstance(v, float) and v.is_integer(): v = int(v)
    if isinstance(v, _dt.datetime):
        v = v.date().isoformat() if v.time() == _dt.time(0) else v.isoformat(sep=" ")
    elif isinstance(v, _dt.date): v = v.isoformat()
    return str(v).replace("\r\n", "\n").replace("\r", "\n").strip()

def xls_rows(wb, sh) -> list[list]:
    """Строки листа xlrd; даты (XL_CELL_DATE) → datetime, как у openpyxl."""
    import xlrd
    out = []
    for r in range(sh.nrows):
        row = []
        for c in range(sh.ncols):
            cell = sh.cell(r, c)
            if cell.ctype == xlrd.XL_CELL_DATE:
                try: row.append(xlrd.xldate.xldate_as_datetime(cell.value, wb.datemode))
                except Exception: row.append(cell.value)
            elif cell.ctype == xlrd.XL_CELL_BOOLEAN: row.append(bool(cell.value))
            elif cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK): row.append(None)
            else: row.append(cell.value)
        out.append(row)
    return out

def read_table(path) -> tuple[list, list]:
    """Прочитать файл (.xlsx/.xlsm/.xls — первый лист, .csv/.txt) → (headers, rows). Публичная, может использоваться Data."""
    path = Path(path); suf = path.suffix.lower()
    if suf in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        rows = [list(r) for r in wb.active.iter_rows(values_only=True)]; wb.close()
    elif suf == ".xls":
        import xlrd
        wb = xlrd.open_workbook(str(path))
        rows = xls_rows(wb, wb.sheet_by_index(0)); wb.release_resources()
    elif suf in (".csv", ".txt"):
        raw = path.read_bytes()
        for enc in ("utf-8-sig", "cp1251"):
            try: text = raw.decode(enc); break
            except UnicodeDecodeError: continue
        else: text = raw.decode("latin-1")
        sample = text[:8192]
        try: delim = csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
        except csv.Error:
            first = sample.splitlines()[0] if sample else ""
            delim = max(";,\t|", key=first.count)
        rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    else:
        raise ValueError(f"неподдерживаемый формат: {suf}")
    while rows and all(_cell(c) == "" for c in rows[0]): rows.pop(0)
    return (rows[0] if rows else []), rows[1:]

def _validate(records, photo_dir):
    """Проверить записи через data_tools.validate_import.validate_records (мягкий импорт).
    Возвращает (errors {idx: [..]}, normalize(rec)->rec, имя валидатора).
    Нет модуля → встроенная минимальная проверка (REQUIRED_MISSING, PHOTO_MISSING) + warning."""
    clean = [{k: v for k, v in r.items() if k != "_row"} for r in records]
    errs = {}
    try:
        from data_tools import validate_import as vi
    except ImportError as e:
        msg = f"data_tools.validate_import недоступен ({e}) — встроенная проверка (fallback)"
        log.warning(msg); warnings.warn(msg, RuntimeWarning, stacklevel=3); vi = None
    if vi is not None:
        for e in vi.validate_records(clean, photos_dir=Path(photo_dir) if photo_dir else None, start_row=0):
            errs.setdefault(e.row, []).append({"field": e.field, "code": e.code, "details": e.details})
        # normalize_record нормализует канонические поля; доп. поля (employee_id…) сохраняем
        return errs, (lambda r: {**r, **vi.normalize_record(r)}), "data_tools.validate_import.validate_records"
    for i, r in enumerate(clean):
        for f in ("last_name", "first_name"):
            if not r.get(f):
                errs.setdefault(i, []).append({"field": f, "code": "REQUIRED_MISSING", "details": "обязательное поле пустое"})
        if photo_dir and not r.get("photo_path"):
            errs.setdefault(i, []).append({"field": "photo_path", "code": "PHOTO_MISSING", "details": "фото не указано"})
    return errs, (lambda r: r), FALLBACK_VALIDATOR

class _Cancel(Exception):
    pass

def _cancelled(cancel):
    if cancel is None: return False
    return bool(cancel.is_set() if hasattr(cancel, "is_set") else cancel())

def _tick(progress, done, total, cancel=None):
    if _cancelled(cancel): raise _Cancel
    if progress is not None and progress(done, total) is False: raise _Cancel

def parse_file(path, mapping=None, labels=None):
    """Файл → (records, labels). record = dict полей + '_row' (номер строки Excel, заголовок=1).
    mapping — см. headers.map_headers (синонимы, ручное назначение, None/'' — исключить колонку).
    labels {key: label} — явные подписи для person_fields."""
    headers, rows = read_table(path)
    return parse_rows(headers, rows, mapping, labels)

def parse_rows(headers, rows, mapping=None, labels=None, first_row: int = 2):
    """(headers, rows) → (records, labels); общий разбор для import_file и import_rows.
    first_row — номер первой строки данных для '_row' (по умолчанию 2: заголовок=1)."""
    keys = map_headers(headers, mapping)
    labs = column_labels(headers, keys, mapping, labels)
    recs = []
    for rn, raw in enumerate(rows, start=first_row):
        vals = [_cell(c) for c in raw]
        if all(v == "" for v in vals): continue
        rec = {"_row": rn}
        for i, k in enumerate(keys):
            if not k: continue
            v = vals[i] if i < len(vals) else ""
            if k == "__fio__":
                for f, part in zip(("last_name", "first_name", "middle_name"), split_fio(v)):
                    if part and not rec.get(f): rec[f] = part
            elif v or k not in rec: rec[k] = v
        rec.setdefault("photo_config", "")
        recs.append(rec)
    return recs, labs

def import_file(con, path, mapping=None, photo_dir=None, validate=True, *, labels=None,
                require_photo=False, progress=None) -> ImportReport:
    """Импортировать файл в persons одной транзакцией. Возвращает ImportReport.

    mapping        см. headers.map_headers; None/'' у заголовка исключает колонку.
    labels         {key: label} для person_fields (перезаписывает существующий label).
    require_photo  False (по умолчанию): записи без фото или с ненайденным файлом фото импортируются,
                   PHOTO_MISSING → report.warnings (photo_path сохраняется как указан),
                   рендер рисует плейсхолдер. True: PHOTO_MISSING — ошибка, строка пропускается
                   (проверяется и без photo_dir).
    progress       callable(done, total) по вставкам; вернул False → отмена: откат всей транзакции,
                   report.cancelled=True, added=0.
    """
    recs, labs = parse_file(path, mapping, labels)
    return import_records(con, recs, labs, photo_dir, validate, labels=labels, require_photo=require_photo,
                          progress=progress)

def import_records(con, recs, labs, photo_dir=None, validate=True, *, labels=None, require_photo=False,
                   progress=None, cancel=None, extra=None) -> ImportReport:
    """Общее ядро импорта (одна транзакция): валидация, person_fields, вставка persons.
    cancel — callable() → True (или объект с is_set(), напр. threading.Event) — отмена с откатом.
    extra  {idx: {'print_mark':…, 'printed_at':…}} — доп. колонки persons (импорт из проектной БД)."""
    rep = ImportReport()
    if validate: verrs, norm, rep.validator = _validate(recs, photo_dir)
    else: verrs, norm, rep.validator = {}, (lambda r: r), "off"
    for i, r in enumerate(recs):
        if require_photo and not r.get("photo_path") and not any(e["code"] == "PHOTO_MISSING" for e in verrs.get(i, [])):
            verrs.setdefault(i, []).append({"field": "photo_path", "code": "PHOTO_MISSING", "details": "фото не указано"})
        if not require_photo and i in verrs:
            # фото не указано (PHOTO_MISSING) или файл не найден (PHOTO_NOT_FOUND от валидатора) — не причина
            # пропускать строку: запись импортируется, в warnings — PHOTO_MISSING (решение Архитектора, этап 13).
            # PHOTO_EMPTY / PHOTO_BROKEN (файл есть, но испорчен) остаются ошибками.
            pm = [e if e["code"] == "PHOTO_MISSING" else
                  {**e, "code": "PHOTO_MISSING", "details": f"файл фото не найден: {e.get('details')} (PHOTO_NOT_FOUND)"}
                  for e in verrs[i] if e["code"] in ("PHOTO_MISSING", "PHOTO_NOT_FOUND")]
            rep.warnings += [{"row": r["_row"], **e} for e in pm]
            verrs[i] = [e for e in verrs[i] if e["code"] not in ("PHOTO_MISSING", "PHOTO_NOT_FOUND")]
            if not verrs[i]: del verrs[i]
    total = len(recs)
    try:
        with con:
            n0 = con.execute("SELECT COALESCE(MAX(sort_order),-1) FROM person_fields").fetchone()[0]
            explicit = set(labels or {})
            for i, (k, lab) in enumerate(labs.items()):
                con.execute("INSERT INTO person_fields(name,label,sort_order) VALUES (?,?,?) ON CONFLICT(name) DO "
                            + ("UPDATE SET label=excluded.label" if k in explicit else "NOTHING"), (k, lab, n0 + 1 + i))
            _tick(progress, 0, total, cancel)
            for idx, r in enumerate(recs):
                if idx in verrs:
                    rep.skipped += 1
                    rep.errors += [{"row": r["_row"], **e} for e in verrs[idx]]
                else:
                    n = norm({k: v for k, v in r.items() if k != "_row"})
                    fields = {k: v for k, v in n.items() if k not in ("photo_path", "photo_config") and v != ""}
                    pc = normalize(n.get("photo_config")) if n.get("photo_config") else DEFAULT
                    ex = (extra or {}).get(idx) or {}
                    cur = con.execute("INSERT INTO persons(fields_json, photo_path, photo_config, print_mark, printed_at) "
                                      "VALUES (?,?,?,?,?)", (json.dumps(fields, ensure_ascii=False),
                                      n.get("photo_path") or None, pc, int(bool(ex.get("print_mark"))), ex.get("printed_at")))
                    rep.added += 1; rep.ids.append(cur.lastrowid)
                _tick(progress, idx + 1, total, cancel)
    except _Cancel:
        return ImportReport(validator=rep.validator, cancelled=True)
    return rep
