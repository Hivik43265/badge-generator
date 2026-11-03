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
