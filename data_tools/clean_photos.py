#!/usr/bin/env python3
"""Копирует валидные фото из <src> в <out> с последовательными именами.
Исходная папка НИКОГДА не изменяется. Никаких crop/scale/rotate."""
from __future__ import annotations
import argparse, csv, re, shutil, sys
from pathlib import Path
from PIL import Image

SUPPORTED = {".jpg", ".jpeg", ".png", ".webp"}
DEFAULT_REPORTS = Path(__file__).resolve().parent.parent / "reports"


def natural_key(name: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def check_file(p: Path) -> str | None:
    """Возвращает причину отбраковки или None."""
    if p.suffix.lower() not in SUPPORTED:
        return "unsupported"
    if p.stat().st_size == 0:
        return "zero_byte"
    try:
        with Image.open(p) as im:
            im.verify()
        with Image.open(p) as im:
            im.load()
    except Exception:
        return "broken"
    return None


def clean(src: Path, out: Path, start: int = 1, digits: int = 4, dry_run: bool = False,
          report_dir: Path | None = None):
    src, out = src.resolve(), out.resolve()
    if not src.is_dir():
        raise SystemExit(f"Нет папки: {src}")
    if out == src or src in out.parents:
        raise SystemExit("Выходная папка не должна совпадать с исходной или лежать внутри неё")
    if out.exists() and any(out.iterdir()) and not dry_run:
        raise SystemExit(f"Выходная папка не пуста: {out}")
    files = sorted((p for p in src.iterdir() if p.is_file()), key=lambda p: natural_key(p.name))
    mapping, rejected, n = [], [], start
    for p in files:
        reason = check_file(p)
        if reason:
            rejected.append((p.name, reason))
            continue
        new = f"{n:0{digits}d}{p.suffix.lower()}"
        mapping.append((p.name, new))
        n += 1
    report_dir = Path(report_dir) if report_dir else out
    if not dry_run:
        out.mkdir(parents=True, exist_ok=True)
        for old, new in mapping:
            shutil.copy2(src / old, out / new)
        report_dir.mkdir(parents=True, exist_ok=True)
        with open(report_dir / "mapping.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["old", "new"]); w.writerows(mapping)
        with open(report_dir / "rejected.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["file", "reason"]); w.writerows(rejected)
    return mapping, rejected


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--digits", type=int, default=4)
    ap.add_argument("--report-dir", default=None, help="куда писать mapping.csv/rejected.csv (по умолчанию <out>)")
    a = ap.parse_args(argv)
    mapping, rejected = clean(Path(a.src), Path(a.out), a.start, a.digits, a.dry_run, a.report_dir)
    for old, new in mapping:
        print(f"{'[dry] ' if a.dry_run else ''}{old} -> {new}")
    for f, r in rejected:
        print(f"REJECT {f}: {r}")
    print(f"OK: {len(mapping)}, отбраковано: {len(rejected)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
