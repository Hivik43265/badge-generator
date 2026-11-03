"""Печать карточек через QPrinter (PyQt6). Frontend показывает QPrintDialog и передаёт сюда QPrinter.

print_cards(con, printer, sides=('front','back'), base_dir=None, ids=None) -> int (число страниц)
 - берёт ТОЛЬКО записи с print_mark=1 (ids, если заданы, дополнительно фильтруют этот набор);
 - каждая сторона рендерится render_card (1011×638) и печатается на своей странице;
 - страница: QPageSize 85.6×54 мм (custom), ориентация Landscape-эквивалент, поля 0,
   FullPage, изображение растягивается на весь paintRect → реальный размер CR80.
PyQt6 импортируется лениво: модуль можно импортировать без Qt.
"""
from __future__ import annotations
from .. import CARD_W_MM, CARD_H_MM
from ..render import render_card_db

def _qimage(pil_img):
    from PyQt6.QtGui import QImage
    data = pil_img.convert("RGB").tobytes("raw", "RGB")
    q = QImage(data, pil_img.width, pil_img.height, 3 * pil_img.width, QImage.Format.Format_RGB888)
    q = q.copy()  # отвязать от буфера Python
    q.setDotsPerMeterX(round(300 / 0.0254)); q.setDotsPerMeterY(round(300 / 0.0254))
    return q

def setup_printer(printer) -> None:
    """Выставить страницу CR80 85.6×54 мм, нулевые поля, FullPage."""
    from PyQt6.QtCore import QSizeF, QMarginsF
    from PyQt6.QtGui import QPageSize, QPageLayout
    size = QPageSize(QSizeF(CARD_W_MM, CARD_H_MM), QPageSize.Unit.Millimeter, "CR80",
                     QPageSize.SizeMatchPolicy.ExactMatch)
    layout = QPageLayout(size, QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0),
                         QPageLayout.Unit.Millimeter, QMarginsF(0, 0, 0, 0))
    printer.setPageLayout(layout)
    printer.setFullPage(True)   # после setPageLayout, иначе сбрасывается

def marked_ids(con, ids=None) -> list[int]:
    rows = [r[0] for r in con.execute("SELECT id FROM persons WHERE print_mark=1 ORDER BY id")]
    return rows if ids is None else [i for i in rows if i in set(ids)]

class PrintResult(int):
    """int (число напечатанных страниц, как раньше) + .missing_photo_ids + .cancelled."""
    missing_photo_ids: list = []
    cancelled: bool = False
    empty_template: bool = False
    warnings: list = []

def _res(n, miss, cancelled=False, tw=(False, [])):
    r = PrintResult(n); r.missing_photo_ids = miss; r.cancelled = cancelled
    r.empty_template, r.warnings = tw[0], list(tw[1]); return r

def print_snapshot(snap, printer, base_dir=None, progress=None, allow_missing_photo=False) -> PrintResult:
    """Напечатать готовый snapshot (см. exporter.snapshot) без БД.
    allow_missing_photo=False и есть записи без фото → MissingPhotosError(.ids) ДО начала печати.
    progress(done,total) → False: printer.abort(), возврат числа отправленных страниц, .cancelled=True."""
    from PyQt6.QtGui import QPainter
    from PyQt6.QtCore import QRectF
    from .exporter import render_job, check_photos, template_warnings
    if not snap: return _res(0, [])
    miss = check_photos(snap, base_dir, allow_missing_photo)
    tw = template_warnings(snap)
    setup_printer(printer)
    total = len(snap)
    if progress is not None and progress(0, total) is False: return _res(0, miss, True, tw)
    p = QPainter()
    if not p.begin(printer): raise RuntimeError("QPainter.begin(printer) не удался")
    done, cancelled = 0, False
    try:
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        for n, job in enumerate(snap):
            if n: printer.newPage()
            p.drawImage(QRectF(printer.paperRect(printer.Unit.DevicePixel)), _qimage(render_job(job, base_dir)))
            done = n + 1
            if progress is not None and progress(done, total) is False:
                printer.abort(); cancelled = True; break
    finally:
        p.end()
    return _res(done, miss, cancelled, tw)

def print_cards(con, printer, sides=("front", "back"), base_dir=None, ids=None, progress=None,
                allow_missing_photo=False) -> PrintResult:
    """Напечатать помеченные (print_mark=1) записи на printer. Возвращает PrintResult (int — число страниц)."""
    from .exporter import snapshot
    ids_ = marked_ids(con, ids)
    if not ids_: return _res(0, [])
    return print_snapshot(snapshot(con, ids_, sides), printer, base_dir, progress, allow_missing_photo)
