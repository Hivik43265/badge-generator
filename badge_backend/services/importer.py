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
from ..fields import normalize_value
from ..db import now_iso
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
    photo_issues: list = field(default_factory=list)     # [{'row','code','file'}] пустые/битые фото (не назначены, не копируются)
    skipped_columns: list = field(default_factory=list)  # [{'key','label'}] колонки без поля в person_fields (D24)
    def as_dict(self): return {"added": self.added, "skipped": self.skipped, "errors": self.errors,
                               "warnings": self.warnings, "ids": self.ids, "validator": self.validator,
                               "cancelled": self.cancelled, "photo_issues": self.photo_issues,
                               "skipped_columns": self.skipped_columns}

def _cell(v, strip: bool = True):
    """Значение ячейки → строка без потерь: только strip и \r\n→\n (внутренние пробелы/переносы сохраняются).
    float-целые → int ('123', не '123.0'); дата без времени → 'YYYY-MM-DD'."""
    import datetime as _dt
    if v is None: return ""
    if isinstance(v, bool): return "1" if v else "0"
    if isinstance(v, float) and v.is_integer(): v = int(v)
    if isinstance(v, _dt.datetime):
        v = v.date().isoformat() if v.time() == _dt.time(0) else v.isoformat(sep=" ")
    elif isinstance(v, _dt.date): v = v.isoformat()
    v = str(v).replace("\r\n", "\n").replace("\r", "\n")
    return v.strip() if strip else v   # D27: validate=False → значение как есть

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

def _yes_no(v):
    from ..fields import normalize_value as _nv
    if v in (None, "") or str(v).strip() == "": return None, None
    sv, err = _nv("bool", v)
    return (None, err) if err else (sv == "1", None)

def _parse_printed_at(v):
    """'ДД.ММ.ГГГГ[ ЧЧ:ММ[:СС]]' или ISO → ISO с локальным смещением (как db.now_iso). '' → None."""
    import datetime as _dt, re as _re
    s = str(v).strip()
    if not s: return None, None
    m = _re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?", s)
    try:
        if m:
            d = _dt.datetime(int(m[3]), int(m[2]), int(m[1]), int(m[4] or 0), int(m[5] or 0), int(m[6] or 0))
        else:
            d = _dt.datetime.fromisoformat(s)
    except ValueError:
        return None, f"не дата печати (ДД.ММ.ГГГГ ЧЧ:ММ:СС): {s!r}"
    if d.tzinfo is None: d = d.astimezone()
    return d.isoformat(timespec="seconds"), None

_PHOTO_SOFT = ("PHOTO_MISSING", "PHOTO_NOT_FOUND", "PHOTO_EMPTY", "PHOTO_BROKEN")

class _Cancel(Exception):
    pass

def _cancelled(cancel):
    if cancel is None: return False
    return bool(cancel.is_set() if hasattr(cancel, "is_set") else cancel())

def _tick(progress, done, total, cancel=None):
    if _cancelled(cancel): raise _Cancel
    if progress is not None and progress(done, total) is False: raise _Cancel

def parse_file(path, mapping=None, labels=None, strip: bool = True):
    """Файл → (records, labels). record = dict полей + '_row' (номер строки Excel, заголовок=1).
    mapping — см. headers.map_headers (синонимы, ручное назначение, None/'' — исключить колонку).
    labels {key: label} — явные подписи для person_fields."""
    headers, rows = read_table(path)
    return parse_rows(headers, rows, mapping, labels, strip=strip)

def parse_rows(headers, rows, mapping=None, labels=None, first_row: int = 2, strip: bool = True):
    """(headers, rows) → (records, labels); общий разбор для import_file и import_rows.
    first_row — номер первой строки данных для '_row' (по умолчанию 2: заголовок=1)."""
    keys = map_headers(headers, mapping)
    labs = column_labels(headers, keys, mapping, labels)
    recs = []
    for rn, raw in enumerate(rows, start=first_row):
        vals = [_cell(c, strip) for c in raw]
        if not vals: continue                      # пустая строка CSV (нет ячеек) — не запись
        if all(v.strip() == "" for v in vals):     # D25: строка из пустых ячеек — ошибка EMPTY_ROW
            recs.append({"_row": rn, "_empty": True}); continue
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
                   PHOTO_MISSING → report.warnings (photo_path сохраняется как указан); пустой/битый файл —
                   импорт с warning PHOTO_EMPTY/PHOTO_BROKEN и пустым photo_path,
                   рендер рисует плейсхолдер. True: PHOTO_MISSING — ошибка, строка пропускается
                   (проверяется и без photo_dir).
    progress       callable(done, total) по вставкам; вернул False → отмена: откат всей транзакции,
                   report.cancelled=True, added=0.
    """
    from .sources import label_mapping
    mapping = {**(mapping or {}), **label_mapping(con, read_table(path)[0], mapping)} or mapping
    recs, labs = parse_file(path, mapping, labels, strip=validate)
    return import_records(con, recs, labs, photo_dir, validate, labels=labels, require_photo=require_photo,
                          progress=progress)

from .photos import resolve_photo_path, photo_file_issue  # noqa: E402

def import_records(con, recs, labs, photo_dir=None, validate=True, *, labels=None, require_photo=False,
                   progress=None, cancel=None, extra=None) -> ImportReport:
    """Общее ядро импорта (одна транзакция): валидация, person_fields, вставка persons.
    cancel — callable() → True (или объект с is_set(), напр. threading.Event) — отмена с откатом.
    extra  {idx: {'print_mark':…, 'printed_at':…}} — доп. колонки persons (импорт из проектной БД)."""
    rep = ImportReport(); clear_photo = set()
    # D24: поля не создаются — только существующие person_fields; прочие колонки пропускаются.
    ftypes = {r[0]: r[1] for r in con.execute("SELECT name, data_type FROM person_fields")}
    image_f = [k for k, t in ftypes.items() if t == "image"]
    keep = set(ftypes) | {"photo_path", "photo_config"}
    empties = {i for i, r in enumerate(recs) if r.pop("_empty", False)}
    # D28: служебные колонки печати → extra (persons.print_mark / printed_at)
    extra = dict(extra or {})
    for i, r in enumerate(recs):
        if not any(k in r for k in ("print_mark", "printed", "printed_at")): continue
        ex = dict(extra.get(i) or {}); err = []
        if "print_mark" in r:
            b, e = _yes_no(r.pop("print_mark"))
            if e: err.append(("print_mark", e))
            elif b is not None: ex["print_mark"] = b
        pa = r.pop("printed_at", None); pd = r.pop("printed", None)
        if pa is not None:
            v, e = _parse_printed_at(pa)
            if e: err.append(("printed_at", e))
            else: ex["printed_at"] = v
        if pd is not None:
            b, e = _yes_no(pd)
            if e: err.append(("printed", e))
            elif b is False: ex["printed_at"] = None
            elif b and not ex.get("printed_at"): ex["printed_at"] = now_iso()
        rep.warnings += [{"row": r["_row"], "field": f, "code": "FIELD_TYPE", "details": d} for f, d in err]
        extra[i] = ex
    seen = []
    for r in recs:
        for k in r:
            if k not in keep and k != "_row" and k not in seen: seen.append(k)
    rep.skipped_columns = [{"key": k, "label": (labs or {}).get(k, k)} for k in seen]
    recs = [{k: v for k, v in r.items() if k in keep or k == "_row"} for r in recs]
    # Вариант (a): значение image-поля — относительный путь, остаётся в fields_json. Файл проверяется
    # тем же правилом resolve_photo_path (база photo_dir): нет файла → warning PHOTO_MISSING (путь сохраняется),
    # пустой/битый → warning PHOTO_EMPTY/PHOTO_BROKEN + photo_issues, значение поля очищается.
    img_issue = {}
    if photo_dir and image_f:
        for i, r in enumerate(recs):
            for k in image_f:
                if r.get(k) in (None, ""): continue
                code = photo_file_issue(resolve_photo_path({"fields": r}, k, photo_dir))
                if code: img_issue.setdefault(i, []).append((k, code))
    if validate: verrs, norm, rep.validator = _validate(recs, photo_dir)
    else: verrs, norm, rep.validator = {}, (lambda r: r), "off"
    for i, r in enumerate(recs):   # «фото не указано» не относится к строке, где фото задано image-полем
        if i in verrs and any(r.get(k) not in (None, "") for k in image_f):
            verrs[i] = [e for e in verrs[i] if not (e["code"] == "PHOTO_MISSING" and e.get("field") == "photo_path")]
            if not verrs[i]: del verrs[i]
    clear_img = {}
    for i, lst in img_issue.items():
        r = recs[i]
        for k, code in lst:
            if code == "PHOTO_NOT_FOUND":
                rep.warnings.append({"row": r["_row"], "field": k, "code": "PHOTO_MISSING",
                                     "details": f"файл фото не найден: {r[k]} (PHOTO_NOT_FOUND)"})
            else:
                rep.warnings.append({"row": r["_row"], "field": k, "code": code,
                                     "details": f"{r[k]}: файл фото {'пустой' if code == 'PHOTO_EMPTY' else 'повреждён'}, фото не назначено"})
                rep.photo_issues.append({"row": r["_row"], "code": code, "file": r[k]})
                clear_img.setdefault(i, set()).add(k)
    for i, r in enumerate(recs):
        if require_photo and not r.get("photo_path") and not any(r.get(k) not in (None, "") and k not in clear_img.get(i, ())
                                                                   for k in image_f) and not any(e["code"] == "PHOTO_MISSING" for e in verrs.get(i, [])):
            verrs.setdefault(i, []).append({"field": "photo_path", "code": "PHOTO_MISSING", "details": "фото не указано"})
        if not require_photo and i in verrs:
            # Решения Архитектора, этап 13: проблемы с фото не причина пропускать строку при require_photo=False.
            #  PHOTO_MISSING (не указано) / PHOTO_NOT_FOUND (файла нет) → warning PHOTO_MISSING, photo_path как указан;
            #  PHOTO_EMPTY / PHOTO_BROKEN (файл пустой/битый) → warning с тем же кодом, photo_path очищается.
            pm = []
            for e in verrs[i]:
                if e["code"] == "PHOTO_MISSING": pm.append(e)
                elif e["code"] == "PHOTO_NOT_FOUND":
                    pm.append({**e, "code": "PHOTO_MISSING", "details": f"файл фото не найден: {e.get('details')} (PHOTO_NOT_FOUND)"})
                elif e["code"] in ("PHOTO_EMPTY", "PHOTO_BROKEN"):
                    pm.append({**e, "details": f"{e.get('details')}: файл фото {'пустой' if e['code'] == 'PHOTO_EMPTY' else 'повреждён'}, фото не назначено"})
                    clear_photo.add(i)
                    rep.photo_issues.append({"row": r["_row"], "code": e["code"], "file": r.get("photo_path") or ""})
            rep.warnings += [{"row": r["_row"], **e} for e in pm]
            verrs[i] = [e for e in verrs[i] if e["code"] not in _PHOTO_SOFT]
            if not verrs[i]: del verrs[i]
    # D25 (Архитектор): обязательных полей нет. Ошибки (строка пропускается) — только FIELD_TYPE и полностью
    # пустая строка (EMPTY_ROW); остальное от валидатора (REQUIRED_MISSING и пр.) — warning, и только для полей проекта.
    for i in list(verrs):
        if i in empties: del verrs[i]; continue
        hard = [e for e in verrs[i] if require_photo and e.get("field") == "photo_path"]
        soft = [e for e in verrs[i] if e not in hard and (e.get("field") in ftypes or e.get("field") in ("photo_path", "photo_config"))]
        rep.warnings += [{"row": recs[i]["_row"], **e} for e in soft]
        if hard: verrs[i] = hard
        else: del verrs[i]
    for i, r in enumerate(recs):
        if i in empties:
            verrs.setdefault(i, []).append({"field": None, "code": "EMPTY_ROW", "details": "пустая строка"})
        else:
            bad = []
            for k, v in r.items():
                if k in ftypes and v not in ("", None):
                    _, err = normalize_value(ftypes[k], v)
                    if err: bad.append({"field": k, "code": "FIELD_TYPE", "details": err})
            if bad: verrs.setdefault(i, []).extend(bad)
    total = len(recs)
    try:
        with con:
            for k, lab in (labels or {}).items():   # явные label — только для существующих полей
                if k in ftypes: con.execute("UPDATE person_fields SET label=? WHERE name=?", (lab, k))
            _tick(progress, 0, total, cancel)
            for idx, r in enumerate(recs):
                if idx in verrs:
                    rep.skipped += 1
                    rep.errors += [{"row": r["_row"], **e} for e in verrs[idx]]
                else:
                    n = norm({k: v for k, v in r.items() if k != "_row"})
                    if idx in clear_photo: n["photo_path"] = None
                    for k in clear_img.get(idx, ()): n[k] = ""
                    fields = {}
                    for k, v in n.items():
                        if k in ("photo_path", "photo_config") or k not in ftypes or v in ("", None): continue
                        sv, _ = normalize_value(ftypes[k], v) if ftypes[k] != "text" else (v, None)
                        if sv != "": fields[k] = sv
                    pc = normalize(n.get("photo_config")) if n.get("photo_config") else DEFAULT
                    ex = extra.get(idx) or {}
                    cur = con.execute("INSERT INTO persons(fields_json, photo_path, photo_config, print_mark, printed_at) "
                                      "VALUES (?,?,?,?,?)", (json.dumps(fields, ensure_ascii=False),
                                      n.get("photo_path") or None, pc, int(bool(ex.get("print_mark"))), ex.get("printed_at")))
                    rep.added += 1; rep.ids.append(cur.lastrowid)
                _tick(progress, idx + 1, total, cancel)
    except _Cancel:
        return ImportReport(validator=rep.validator, cancelled=True)
    return rep
