"""Этап 8: D1 (допуск страницы ±0.15 мм), D2 (перенос по дефису, порядок), D3 (без частичных строк, «…»)."""
import json, warnings, pytest
from PIL import Image, ImageDraw
from badge_backend.render import render_card, _wrap, _fit_text, get_font, ELLIPSIS
from badge_backend import DPI

TOL_MM = 0.15
def page_size_ok(w_mm, h_mm, tol=TOL_MM):
    """Решение Архитектора по D1: CR80 85.6×54 мм с допуском ±0.15 мм."""
    return abs(w_mm - 85.6) <= tol + 1e-9 and abs(h_mm - 54.0) <= tol + 1e-9

# ---------- D1 ----------
def test_page_tolerance_boundary():
    assert page_size_ok(85.6 + 0.15, 54.0 - 0.15) and page_size_ok(85.725, 53.975)
    assert not page_size_ok(85.6 + 0.16, 54.0) and not page_size_ok(85.6, 54.0 - 0.16)

def test_qprinter_pdf_page_within_tolerance(demo_db, tmp_path):
    pytest.importorskip("PyQt6.QtPrintSupport")
    import re
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtPrintSupport import QPrinter
    from badge_backend.services.print_service import print_cards
    app = QApplication.instance() or QApplication([])
    pr = QPrinter(QPrinter.PrinterMode.HighResolution); pr.setResolution(300)
    pr.setOutputFormat(QPrinter.OutputFormat.PdfFormat); pr.setOutputFileName(str(tmp_path / "t.pdf"))
    c, ids, d = demo_db
    assert print_cards(c, pr, ("front",), base_dir=d, allow_missing_photo=True) == 2
    boxes = re.findall(rb"/MediaBox\s*\[\s*([\d.\s]+)\]", (tmp_path / "t.pdf").read_bytes())
    assert boxes
    for b in boxes:
        x0, y0, x1, y1 = map(float, b.split())
        assert page_size_ok((x1 - x0) / 72 * 25.4, (y1 - y0) / 72 * 25.4), b

# ---------- D2 ----------
def _d(): return ImageDraw.Draw(Image.new("RGB", (4, 4)))

def test_wrap_on_hyphen_keeps_hyphen():
    lines, cut = _wrap(_d(), "Римский-Корсаков", get_font(60), 330)
    assert lines == ["Римский-", "Корсаков"] and not cut

@pytest.mark.parametrize("text,first", [("ООО/Ромашка", "ООО/"), ("Альфа—Бетагамма", "Альфа—"),
                                        ("Альфа–Бетагамма", "Альфа–")])
def test_wrap_on_dashes_and_slash(text, first):
    lines, cut = _wrap(_d(), text, get_font(60), 200)
    assert lines[0] == first and not cut

def test_spaces_before_hyphens():
    """Если слово целиком влезает на новую строку — переносим по пробелу, дефис не трогаем."""
    lines, _ = _wrap(_d(), "Николай Римский-Корсаков", get_font(30), 300)
    assert lines == ["Николай", "Римский-Корсаков"]

def _fit(text, w, h, pt, min_pt=8):
    return _fit_text(_d(), text, w, h, pt * DPI / 72, min_pt * DPI / 72, None, False, None, True, 1.0)

def test_order_shrink_before_char_split():
    """Слово без разрывов, влезающее при меньшем кегле, уменьшается, а не режется."""
    f, lines, *_, notes = _fit("Константинопольский", 400, 200, 20)
    assert lines == ["Константинопольский"] and notes == []
    assert f.size < round(20 * DPI / 72)

def test_double_surname_no_warning_in_frame():
    w, h = 480, 200
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        f, lines, *_, notes = _fit("Константинопольский-Водопьянов", w, h, 14)
    assert notes == [] and lines[0].endswith("-") and all("-" not in l[:-1] for l in lines)

def test_char_split_only_at_min_size_with_warning():
    w, h = 150, 300
    f, lines, *_, notes = _fit("Превысокомногорассмотрительствующий", w, h, 14)
    assert f.size == round(8 * DPI / 72)
    assert len(lines) > 1 and any("символам" in n for n in notes)
    with pytest.warns(RuntimeWarning, match="символам"):
        _render("Превысокомногорассмотрительствующий", w, h, font_size=14)

# ---------- D3 ----------
def _render(text, w, h, x=100, y=100, **st):
    el = dict(id=1, type="text", x=x, y=y, w=w, h=h, static_value=text, style_json=json.dumps(st))
    return render_card(None, [el], background={"color": "#FFFFFF"})

LONG = "Ведущий инженер-конструктор отдела перспективных разработок и испытаний изделий"

def test_truncate_whole_lines_with_ellipsis():
    f, lines, ys, ws, bb, notes = _fit(LONG, 300, 100, 10, 10)
    assert notes and lines and lines[-1].endswith(ELLIPSIS)
    assert bb[3] - bb[1] <= 100                       # видимые строки целиком в рамке

def test_no_partial_line_pixels():
    """Обрезанный рендер == рендеру только видимых строк (wrap выкл.), т.е. нет обрывков глифов."""
    w, h = 300, 100
    _, lines, *_ = _fit(LONG, w, h, 10, 10)
    with pytest.warns(RuntimeWarning, match="строк"):
        a = _render(LONG, w, h, font_size=10, min_size=10)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        b = _render("\n".join(lines), w, h, font_size=10, min_size=10, wrap=False)
    assert a.tobytes() == b.tobytes()
    inv = Image.eval(a.convert("L"), lambda v: 255 - v).getbbox()
    assert inv[1] >= 100 and inv[3] <= 100 + h and inv[2] <= 100 + w

def test_no_line_fits_draws_nothing():
    with pytest.warns(RuntimeWarning):
        im = _render("Йурд", 200, 10, font_size=10)
    assert Image.eval(im.convert("L"), lambda v: 255 - v).getbbox() is None
