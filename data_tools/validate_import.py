#!/usr/bin/env python3
"""Валидация записей persons (канонические имена полей).
Маппинг заголовков и чтение Excel — зона Backend. Здесь: чистые функции + тонкий CLI для CSV
с каноническими заголовками. Обработки изображений нет (только проверка, что файл открывается)."""
from __future__ import annotations
import argparse, csv, re, sys
from dataclasses import dataclass, astuple
from pathlib import Path
from PIL import Image

FIELDS = ["last_name", "first_name", "middle_name", "position", "department",
          "photo_path", "email", "phone", "photo_config"]
REQUIRED = ["last_name", "first_name"]
DEFAULT_PHOTO_CONFIG = "0;0;1.0;0;0;0"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
INT_RE = re.compile(r"^-?\d+$")
NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")
DEFAULT_REPORT = Path(__file__).resolve().parent.parent / "reports" / "report.csv"


@dataclass(frozen=True)
class Error:
    row: int      # номер записи (в CLI — номер строки CSV, заголовок = 1)
    field: str
    code: str
    details: str = ""


def _s(v) -> str:
    return re.sub(r"\s+", " ", "" if v is None else str(v)).strip()


def _dupkey(rec) -> tuple:
    return tuple(_s(rec.get(f)).lower().replace("ё", "е") for f in ("last_name", "first_name", "middle_name", "email"))


def check_photo_config(v: str) -> bool:
    v = _s(v)
    if v == "":
        return True
    parts = [p.strip() for p in v.split(";")]
    if len(parts) != 6:
        return False
    return all((INT_RE if i in (3, 4) else NUM_RE).match(p) for i, p in enumerate(parts))


def check_photo(p: Path) -> str | None:
    if not p.is_file():
        return "PHOTO_NOT_FOUND"
    if p.stat().st_size == 0:
        return "PHOTO_EMPTY"
    try:
        with Image.open(p) as im:
            im.verify()
    except Exception:
        return "PHOTO_BROKEN"
    return None


def check_columns(headers) -> list[Error]:
    hs = {_s(h) for h in headers}
    return [Error(1, f, "MISSING_COLUMN", "нет обязательной колонки") for f in REQUIRED if f not in hs]


def validate_record(rec: dict, row: int, photos_dir: Path | None = None) -> list[Error]:
    errs = []
    for f in REQUIRED:
        if not _s(rec.get(f)):
            errs.append(Error(row, f, "REQUIRED_MISSING", "обязательное поле пустое"))
    email, phone = _s(rec.get("email")), _s(rec.get("phone"))
    if email and not EMAIL_RE.match(email):
        errs.append(Error(row, "email", "EMAIL_INVALID", email))
    if phone and (not re.fullmatch(r"\+?[\d\s()\-]+", phone) or not 10 <= len(re.sub(r"\D", "", phone)) <= 15):
        errs.append(Error(row, "phone", "PHONE_INVALID", phone))
    if not check_photo_config(rec.get("photo_config")):
        errs.append(Error(row, "photo_config", "PHOTO_CONFIG_INVALID", _s(rec.get("photo_config"))))
    photo = _s(rec.get("photo_path"))
    if photo:
        p = Path(photo)
        if not p.is_absolute() and photos_dir:
            p = Path(photos_dir) / p
        code = check_photo(p)
        if code:
            errs.append(Error(row, "photo_path", code, photo))
    elif photos_dir:
        errs.append(Error(row, "photo_path", "PHOTO_MISSING", "фото не указано"))
    return errs


def validate_records(records: list[dict], photos_dir: Path | None = None, start_row: int = 1) -> list[Error]:
    """Проверяет список записей; номер записи = start_row + индекс."""
    errors, seen = [], {}
    for i, rec in enumerate(records):
        row = start_row + i
        errors += validate_record(rec, row, photos_dir)
        if _s(rec.get("last_name")):
            k = _dupkey(rec)
            if k in seen:
                errors.append(Error(row, "*", "DUPLICATE", f"дубль записи {seen[k]}"))
            else:
                seen[k] = row
    return errors


def normalize_record(rec: dict) -> dict:
    out = {f: _s(rec.get(f)) for f in FIELDS}
    out["photo_config"] = out["photo_config"] or DEFAULT_PHOTO_CONFIG
    return out


def valid_records(records, errors, start_row: int = 1) -> list[dict]:
    bad = {e.row for e in errors}
    return [normalize_record(r) for i, r in enumerate(records) if start_row + i not in bad]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file", help="CSV (UTF-8) с каноническими заголовками")
    ap.add_argument("--photos")
    ap.add_argument("--report", default=str(DEFAULT_REPORT))
    ap.add_argument("--valid", default=None, help="путь valid.csv (по умолчанию рядом с отчётом)")
    a = ap.parse_args(argv)
    with open(a.file, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        records = [r for r in reader if any(_s(v) for v in r.values())]
    errors = check_columns(headers)
    if not errors:
        errors = validate_records(records, Path(a.photos) if a.photos else None, start_row=2)
        valid = valid_records(records, errors, start_row=2)
    else:
        valid = []
    rep = Path(a.report); rep.parent.mkdir(parents=True, exist_ok=True)
    with open(rep, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["row", "field", "code", "details"]); w.writerows(astuple(e) for e in errors)
    vp = Path(a.valid) if a.valid else rep.parent / "valid.csv"
    with open(vp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader(); w.writerows(valid)
    for e in errors:
        print(f"row {e.row}: {e.code} [{e.field}] {e.details}")
    print(f"Валидных: {len(valid)}, ошибок: {len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
