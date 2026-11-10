import re
from pathlib import Path
import pytest
pytest.importorskip("PyQt6.QtPrintSupport")
from PyQt6.QtWidgets import QApplication
from PyQt6.QtPrintSupport import QPrinter
from badge_backend.services.print_service import print_cards, marked_ids

@pytest.fixture(scope="module")
def app(): return QApplication.instance() or QApplication([])

def _pdf(tmp_path, name):
    pr = QPrinter(QPrinter.PrinterMode.HighResolution)
    pr.setOutputFormat(QPrinter.OutputFormat.PdfFormat); pr.setOutputFileName(str(tmp_path / name))
    pr.setResolution(300)
    return pr

def _boxes(path):
    data = Path(path).read_bytes()
    pages = len(re.findall(rb"/Type\s*/Page[^s]", data))
    boxes = [tuple(map(float, b.split())) for b in re.findall(rb"/MediaBox\s*\[\s*([\d.\s]+)\]", data)]
    return pages, boxes

def test_print_only_marked_each_side_own_page(app, demo_db, tmp_path):
    c, ids, d = demo_db
    assert marked_ids(c) == ids[:2]
    pr = _pdf(tmp_path, "p.pdf")
    assert print_cards(c, pr, ("front", "back"), base_dir=d, allow_missing_photo=True) == 4
    pages, boxes = _boxes(tmp_path / "p.pdf"); assert pages == 4
    for b in boxes:
        w, h = (b[2] - b[0]) / 72 * 25.4, (b[3] - b[1]) / 72 * 25.4
        assert abs(w - 85.6) < 0.3 and abs(h - 54.0) < 0.3, (w, h)
    lay = pr.pageLayout()
    assert lay.margins().left() == lay.margins().top() == 0 and pr.fullPage()

def test_print_front_only_and_ids_filter(app, demo_db, tmp_path):
    c, ids, d = demo_db
    pr = _pdf(tmp_path, "f.pdf")
    assert print_cards(c, pr, "front", base_dir=d, ids=[ids[1], ids[2]], allow_missing_photo=True) == 1  # ids[2] не помечен
    assert _boxes(tmp_path / "f.pdf")[0] == 1

def test_print_nothing_marked(app, con, tmp_path):
    assert print_cards(con, _pdf(tmp_path, "n.pdf")) == 0

def test_print_missing_photo_strict_nothing_printed(app, demo_db, tmp_path):
    from badge_backend.services.exporter import MissingPhotosError
    c, ids, d = demo_db
    pr = _pdf(tmp_path, "s.pdf")
    with pytest.raises(MissingPhotosError) as ei: print_cards(c, pr, base_dir=d)
    assert ei.value.ids == [ids[1]] and not (tmp_path / "s.pdf").exists()

def test_print_missing_photo_allowed_reports_ids(app, demo_db, tmp_path):
    c, ids, d = demo_db
    r = print_cards(c, _pdf(tmp_path, "a.pdf"), base_dir=d, allow_missing_photo=True)
    assert r == 4 and r.missing_photo_ids == [ids[1]] and not r.cancelled

def test_print_progress_cancel_and_snapshot(app, demo_db, tmp_path):
    from badge_backend.services.exporter import snapshot
    from badge_backend.services.print_service import print_snapshot
    c, ids, d = demo_db
    r = print_cards(c, _pdf(tmp_path, "c.pdf"), base_dir=d, allow_missing_photo=True, progress=lambda a, b: a < 2)
    assert r == 2 and r.cancelled
    calls = []
    r = print_snapshot(snapshot(c, [ids[0]], "front"), _pdf(tmp_path, "one.pdf"), base_dir=d,
                       progress=lambda a, b: calls.append((a, b)))
    assert r == 1 and calls[-1] == (1, 1) and _boxes(tmp_path / "one.pdf")[0] == 1


def test_print_overrides_a4_page_to_cr80(app, demo_db, tmp_path):
    """После QPrintDialog принтер часто остаётся с A4 — print_cards должен выставить CR80."""
    from PyQt6.QtCore import QMarginsF
    from PyQt6.QtGui import QPageLayout, QPageSize
    from badge_backend.services.print_service import pdf_pages_are_cr80, pdf_page_sizes_mm
    c, ids, d = demo_db
    pr = QPrinter(QPrinter.PrinterMode.HighResolution)
    pr.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    pr.setOutputFileName(str(tmp_path / "from_a4.pdf"))
    pr.setResolution(300)
    a4 = QPageSize(QPageSize.PageSizeId.A4)
    pr.setPageLayout(QPageLayout(a4, QPageLayout.Orientation.Portrait,
                                 QMarginsF(10, 10, 10, 10), QPageLayout.Unit.Millimeter))
    pr.setFullPage(False)
    assert print_cards(c, pr, ("front",), base_dir=d, allow_missing_photo=True) == 2
    sizes = pdf_page_sizes_mm(tmp_path / "from_a4.pdf")
    assert pdf_pages_are_cr80(tmp_path / "from_a4.pdf"), sizes
    for w, h in sizes:
        assert abs(w - 210) > 5 and abs(h - 297) > 5, (w, h)
    assert pr.fullPage() and pr.pageLayout().margins().left() == 0

def test_cr80_paint_rect_not_stretched_to_a4(app, tmp_path):
    """Даже если страница принтера A4, область рисунка — 85.6×54 мм, не весь лист."""
    from PyQt6.QtCore import QMarginsF
    from PyQt6.QtGui import QPageLayout, QPageSize
    from badge_backend.services.print_service import _cr80_paint_rect
    pr = QPrinter(QPrinter.PrinterMode.HighResolution)
    pr.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    pr.setOutputFileName(str(tmp_path / "n.pdf"))
    pr.setResolution(300)
    a4 = QPageSize(QPageSize.PageSizeId.A4)
    pr.setPageLayout(QPageLayout(a4, QPageLayout.Orientation.Portrait,
                                 QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter))
    r = _cr80_paint_rect(pr)
    paper = pr.paperRect(pr.Unit.DevicePixel)
    assert r.width() < paper.width() * 0.6 and r.height() < paper.height() * 0.4
    mm = pr.paperRect(pr.Unit.Millimeter)
    assert abs(r.width() / paper.width() * mm.width() - 85.6) < 0.3
    assert abs(r.height() / paper.height() * mm.height() - 54.0) < 0.3


def test_setup_printer_landscape_cr80_page(app, tmp_path):
    """Страница после setup_printer — альбомная CR80 85.6×54, область рисунка не шире листа."""
    from PyQt6.QtGui import QPageLayout
    from badge_backend import CARD_W_MM, CARD_H_MM
    from badge_backend.services.print_service import setup_printer, _cr80_paint_rect
    pr = _pdf(tmp_path, "land.pdf")
    setup_printer(pr)
    lay = pr.pageLayout()
    assert lay.orientation() == QPageLayout.Orientation.Landscape
    assert lay.margins().left() == lay.margins().top() == 0 and pr.fullPage()
    page = lay.fullRect(QPageLayout.Unit.Millimeter)
    assert abs(page.width() - CARD_W_MM) < 0.3 and abs(page.height() - CARD_H_MM) < 0.3
    assert page.width() > page.height()
    mm = pr.paperRect(pr.Unit.Millimeter)
    assert mm.width() > mm.height()
    assert abs(mm.width() - 85.6) < 0.5 and abs(mm.height() - 54.0) < 0.5
    r = _cr80_paint_rect(pr)
    paper = pr.paperRect(pr.Unit.DevicePixel)
    assert r.width() <= paper.width() + 1 and r.height() <= paper.height() + 1
    assert abs(r.width() / paper.width() * mm.width() - 85.6) < 0.3
    assert abs(r.height() / paper.height() * mm.height() - 54.0) < 0.3
    assert r.width() > r.height()
