"""Экспорт карточек: PNG 300 DPI и PDF CR80 (страница = сторона, 85.6×54 мм при 300 DPI).

Для фоновых потоков: snapshot(con, ...) собирается в GUI-потоке (единственное обращение к БД),
затем export_*_from_snapshot(snap, ...) работают без соединения (подходит и для ':memory:').
progress: callable(done, total); вернул False → отмена.
"""
from __future__ import annotations
from pathlib import Path
from ..render import render_card, load_elements, load_background

import os
from pathlib import PosixPath, WindowsPath

class MissingPhotosError(RuntimeError):
    """Среди записей есть без фото или с недоступным файлом; .ids — их id. Выбрасывается ДО экспорта/печати."""
    def __init__(self, ids):
        self.ids = list(ids)
        super().__init__(f"записи без фото или с недоступным файлом: {self.ids}")

class ExportResult(list):
    """list[Path] (как раньше) + .missing_photo_ids + .cancelled + .empty_template + .warnings."""
    missing_photo_ids: list = []
    cancelled: bool = False
    empty_template: bool = False
    warnings: list = []

class PdfResult(WindowsPath if os.name == "nt" else PosixPath):
    """Path к PDF (как раньше) + .missing_photo_ids + .empty_template + .warnings."""
    missing_photo_ids: list = []
    empty_template: bool = False
    warnings: list = []

EMPTY_TEMPLATE_WARNING = "шаблон пуст: нет элементов ни на одной экспортируемой стороне"

def empty_template_sides(snap) -> list[str]:
    """Стороны snapshot без элементов (порядок сохранён)."""
    out = []
    for job in snap:
        if not job["elements"] and job["side"] not in out: out.append(job["side"])
    return out

def template_warnings(snap) -> tuple[bool, list[str]]:
    """→ (empty_template, warnings). empty_template=True, если ВО ВСЕХ сторонах snapshot нет элементов.
    Пишет log.warning + warnings.warn(RuntimeWarning), без исключения."""
    import logging, warnings as _w
    if not snap: return False, []
    sides = {j["side"] for j in snap}; empty = empty_template_sides(snap)
    msgs = []
    if set(empty) == sides: msgs.append(EMPTY_TEMPLATE_WARNING)
    else: msgs += [f"сторона '{s}' шаблона пуста" for s in empty]
    for m in msgs:
        logging.getLogger(__name__).warning(m); _w.warn(m, RuntimeWarning, stacklevel=3)
    return set(empty) == sides, msgs

def _photo_ok(photo_path, base_dir) -> bool:
    if not photo_path: return False
    p = Path(photo_path)
    if not p.is_absolute() and base_dir: p = Path(base_dir) / p
    if not p.is_file() or p.stat().st_size == 0: return False
    try:
        from PIL import Image
        with Image.open(p) as im: im.verify()
        return True
    except Exception:
        return False

def missing_photos_in_snapshot(snap, base_dir=None) -> list[int]:
    """id записей snapshot, у которых photo_path пуст или файл недоступен/битый (порядок сохранён, без повторов)."""
    seen, out = set(), []
    for job in snap:
        p = job["person"]
        if p["id"] in seen: continue
        seen.add(p["id"])
        if not _photo_ok(p.get("photo_path"), base_dir): out.append(p["id"])
    return out

def missing_photos(con, ids=None, base_dir=None) -> list[int]:
    """Предпроверка для UI: id записей без фото/с недоступным файлом. ids=None → все print_mark=1."""
    return missing_photos_in_snapshot(snapshot(con, ids, "front"), base_dir)

def check_photos(snap, base_dir, allow_missing_photo):
    """→ missing ids; при allow_missing_photo=False и непустом списке — MissingPhotosError."""
    miss = missing_photos_in_snapshot(snap, base_dir)
    if miss and not allow_missing_photo: raise MissingPhotosError(miss)
    return miss

def _ids(con, ids):
    if ids is None:
        return [r[0] for r in con.execute("SELECT id FROM persons WHERE print_mark=1 ORDER BY id")]
    return list(ids)

def _sides(sides):
    sides = [sides] if isinstance(sides, str) else list(sides)
    bad = set(sides) - {"front", "back"}
    if bad or not sides: raise ValueError(f"sides: только 'front'/'back', получено {sides}")
    return sides

def snapshot(con, ids=None, sides=("front", "back")) -> list[dict]:
    """Собрать готовые данные для рендера без БД. ids=None → все print_mark=1 (порядок по id),
    иначе — в заданном порядке (несуществующие id пропускаются).
    Возвращает список заданий [{'person': dict, 'side': str, 'elements': list[dict], 'background': dict|None}]
    — по одному на (запись, сторона). elements/background — общие объекты для одной стороны (только чтение)."""
    sides = _sides(sides)
    els = {s: load_elements(con, s) for s in sides}; bgs = {s: load_background(con, s) for s in sides}
    out = []
    for pid in _ids(con, ids):
        r = con.execute("SELECT * FROM persons WHERE id=?", (pid,)).fetchone()
        if r is None: continue
        p = dict(r)
        for s in sides: out.append({"person": p, "side": s, "elements": els[s], "background": bgs[s]})
    return out

def render_job(job, base_dir=None):
    return render_card(job["person"], job["elements"], job["side"], job["background"], base_dir)

def _tick(progress, done, total):
    return progress is None or progress(done, total) is not False

def export_png_from_snapshot(snap, out_dir=".", base_dir=None, progress=None, allow_missing_photo=False) -> ExportResult:
    """PNG 1011×638 (dpi=300) <out_dir>/<id>_<side>.png. Возвращает ExportResult (list[Path]).
    Отмена → уже сохранённые файлы остаются, .cancelled=True."""
    miss = check_photos(snap, base_dir, allow_missing_photo)
    res = ExportResult(); res.missing_photo_ids = miss
    res.empty_template, res.warnings = template_warnings(snap)
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    total = len(snap)
    if not _tick(progress, 0, total): res.cancelled = True; return res
    for n, job in enumerate(snap, 1):
        p = out / f"{job['person']['id']}_{job['side']}.png"
        render_job(job, base_dir).save(p, dpi=(300, 300)); res.append(p)
        if not _tick(progress, n, total): res.cancelled = True; break
    return res

def export_pdf_from_snapshot(snap, out_path="cards.pdf", base_dir=None, progress=None,
                             allow_missing_photo=False) -> PdfResult | None:
    """Один PDF, страница на задание, точно CR80. Возвращает PdfResult (Path) с .missing_photo_ids.
    Отмена → файл не создаётся, возврат None."""
    if not snap: raise ValueError("нечего экспортировать (нет записей)")
    miss = check_photos(snap, base_dir, allow_missing_photo)
    et, tw = template_warnings(snap)
    total = len(snap); pages = []
    if not _tick(progress, 0, total): return None
    for n, job in enumerate(snap, 1):
        pages.append(render_job(job, base_dir))
        if not _tick(progress, n, total): return None
    out = Path(out_path); out.parent.mkdir(parents=True, exist_ok=True)
    pages[0].save(out, "PDF", resolution=300.0, save_all=True, append_images=pages[1:])
    r = PdfResult(out); r.missing_photo_ids = miss
    r.empty_template, r.warnings = et, tw
    return r

def export_png(con, ids=None, out_dir=".", sides=("front", "back"), base_dir=None, progress=None,
               allow_missing_photo=False) -> ExportResult:
    """Сохранить PNG как <out_dir>/<id>_<side>.png. ids=None → все print_mark=1.
    allow_missing_photo=False и есть записи без фото → MissingPhotosError(.ids) до записи файлов."""
    return export_png_from_snapshot(snapshot(con, ids, sides), out_dir, base_dir, progress, allow_missing_photo)

def export_pdf(con, ids=None, out_path="cards.pdf", sides=("front", "back"), base_dir=None, progress=None,
               allow_missing_photo=False):
    """Один PDF: по странице на сторону, страница точно CR80 (300 DPI). См. export_png про фото."""
    return export_pdf_from_snapshot(snapshot(con, ids, sides), out_path, base_dir, progress, allow_missing_photo)


def set_print_mark(con, ids, value: bool = True) -> int:
    """Флаг «к печати»: print_mark=1 (value=True) или 0 (False). printed_at не трогает. → число строк."""
    ids = list(ids)
    if not ids: return 0
    with con:
        cur = con.execute(f"UPDATE persons SET print_mark=? WHERE id IN ({','.join('?' * len(ids))})",
                          (1 if value else 0, *ids))
    return cur.rowcount

def mark_printed(con, ids) -> int:
    """«Напечатано»: одной транзакцией print_mark=0 и printed_at=db.now_iso() (ISO 8601 с локальным
    смещением). При ошибке — откат. → число строк. Флаг «к печати» — только через set_print_mark."""
    from ..db import now_iso
    ids = list(ids)
    if not ids: return 0
    with con:
        cur = con.execute(f"UPDATE persons SET print_mark=0, printed_at=? WHERE id IN ({','.join('?' * len(ids))})",
                          (now_iso(), *ids))
    return cur.rowcount
