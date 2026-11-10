"""Печать карточек через QPrinter (PyQt6). Frontend показывает QPrintDialog и передаёт сюда QPrinter.

print_cards(con, printer, sides=('front','back'), base_dir=None, ids=None) -> int (число страниц)
 - берёт ТОЛЬКО записи с print_mark=1 (ids, если заданы, дополнительно фильтруют этот набор);
 - каждая сторона рендерится render_card (1011×638) и печатается на своей странице;
 - страница: QPageSize 85.6×53.98 мм (ISO ID-1 / CARD_H_MM, FuzzyMatch), поля 0, FullPage;
   рисуется в прямоугольник ровно CR80 мм (не растягивается под paperRect — у принтера
   он может остаться A4, если драйвер не принял custom size).
QPrinter/QPainter нельзя уводить в QThread: setup_printer и print_snapshot работают
только в главном потоке приложения (иначе RuntimeError вместо вылета на Windows).
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


def _require_gui_thread() -> None:
    """QPrinter/QPainter нельзя уводить в QThread: только главный поток приложения."""
    from PyQt6.QtCore import QCoreApplication, QThread
    app = QCoreApplication.instance()
    # is — как сравнение объекта потока; == нужен, если PyQt даёт разные обёртки одного QThread.
    if app is None or (QThread.currentThread() is not app.thread() and QThread.currentThread() != app.thread()):
        raise RuntimeError("печать на принтер возможна только из главного потока")

def setup_printer(printer) -> None:
    """Выставить страницу CR80 85.6×54 мм (альбомная), нулевые поля, FullPage.

    FuzzyMatch, не ExactMatch: карточный принтер часто заявляет ISO ID-1 85.60×53.98 мм.
    ExactMatch с высотой, отличающейся на сотые мм, не совпадает — setPageLayout тихо отказывает, страница
    остаётся A4 (после QPrintDialog), и drawImage на весь paperRect растягивал пропуск до A4.
    Ориентация только Landscape: QPageSize хранит размер книжно (53.98×85.6), Portrait обрезал бы карточку справа.
    """
    from PyQt6.QtCore import QSizeF, QMarginsF
    from PyQt6.QtGui import QPageSize, QPageLayout
    _require_gui_thread()
    size = QPageSize(QSizeF(CARD_W_MM, CARD_H_MM), QPageSize.Unit.Millimeter, "CR80",
                     QPageSize.SizeMatchPolicy.FuzzyMatch)
    margins = QMarginsF(0, 0, 0, 0)
    # QPageSize всегда хранит размер в книжном виде (меньшая сторона — ширина):
    # 85.6×53.98 превращается в 53.98×85.6. Portrait оставил бы страницу вертикальной
    # и обрезал правый край карточки. Карточка всегда горизонтальная — только Landscape.
    layout = QPageLayout(size, QPageLayout.Orientation.Landscape, margins,
                         QPageLayout.Unit.Millimeter, margins)
    if not printer.setPageLayout(layout):
        printer.setPageSize(size)
        printer.setPageOrientation(QPageLayout.Orientation.Landscape)
        printer.setPageMargins(margins, QPageLayout.Unit.Millimeter)
    printer.setFullPage(True)   # после setPageLayout, иначе сбрасывается

def _cr80_paint_rect(printer):
    """Прямоугольник ровно CARD_W_MM×CARD_H_MM в DevicePixel (не весь paperRect)."""
    from PyQt6.QtCore import QRectF
    paper_mm = printer.paperRect(printer.Unit.Millimeter)
    paper_px = printer.paperRect(printer.Unit.DevicePixel)
    if paper_mm.width() > 0 and paper_mm.height() > 0:
        return QRectF(0, 0,
                      CARD_W_MM * paper_px.width() / paper_mm.width(),
                      CARD_H_MM * paper_px.height() / paper_mm.height())
    dpi = printer.resolution() or 300
    return QRectF(0, 0, CARD_W_MM / 25.4 * dpi, CARD_H_MM / 25.4 * dpi)

def pdf_page_sizes_mm(path) -> list[tuple[float, float]]:
    """Размеры страниц PDF (мм) по MediaBox. Без дополнительных зависимостей.
    Для --self-test: проверить, что страница печати/экспорта равна CR80."""
    import re
    from pathlib import Path
    boxes = re.findall(rb"/MediaBox\s*\[\s*([\d.\s]+)\]", Path(path).read_bytes())
    out = []
    for b in boxes:
        x0, y0, x1, y1 = map(float, b.split())
        out.append(((x1 - x0) / 72 * 25.4, (y1 - y0) / 72 * 25.4))
    return out

def pdf_pages_are_cr80(path, tol: float = 0.15) -> bool:
    """Все страницы PDF имеют размер CR80 (CARD_W_MM×CARD_H_MM, допуск D1 ±0.15 мм)."""
    sizes = pdf_page_sizes_mm(path)
    return bool(sizes) and all(abs(w - CARD_W_MM) <= tol and abs(h - CARD_H_MM) <= tol for w, h in sizes)

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
    from .exporter import render_job, check_photos, template_warnings
    if not snap: return _res(0, [])
    miss = check_photos(snap, base_dir, allow_missing_photo)
    tw = template_warnings(snap)
    setup_printer(printer)
    total = len(snap)
    if progress is not None and progress(0, total) is False: return _res(0, miss, True, tw)
    _require_gui_thread()   # QPrinter/QPainter нельзя уводить в QThread
    p = QPainter()
    if not p.begin(printer): raise RuntimeError("QPainter.begin(printer) не удался")
    done, cancelled = 0, False
    try:
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        for n, job in enumerate(snap):
            if n: printer.newPage()
            p.drawImage(_cr80_paint_rect(printer), _qimage(render_job(job, base_dir)))
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
