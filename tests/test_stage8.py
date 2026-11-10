"""Этап 8: D1 (допуск страницы ±0.15 мм), D2 (перенос по дефису), D3 (обрезка по рамке без автоподбора)."""
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

def test_exact_size_no_shrink():
    """Кегль не уменьшается: слово рисуется ровно заданным размером."""
    f, lines, *_, notes = _fit("Константинопольский", 400, 200, 20)
    assert f.size == round(20 * DPI / 72)
    # если слово влезает в 400 px при 20 pt — одна строка без notes; иначе только перенос, не уменьшение
    if notes:
        assert "уменьш" not in " ".join(notes).lower()
    else:
        assert lines == ["Константинопольский"]

def test_double_surname_hyphen_wrap_at_exact_size():
    """Части двойной фамилии, влезающие при заданном кегле, переносятся по дефису без уменьшения.
    (Раньше ширина 480 px хватала только после автоподбора: «Константинопольский-» при 14 pt ≈ 706 px.)"""
    w, h = 800, 200
    f, lines, *_, notes = _fit("Константинопольский-Водопьянов", w, h, 14)
    assert f.size == round(14 * DPI / 72)
    assert notes == [] and lines[0].endswith("-") and all("-" not in l[:-1] for l in lines)

def test_char_split_at_exact_size_with_warning():
    """Слово шире рамки режется по символам на заданном кегле, без уменьшения до min_size."""
    w, h = 150, 300
    f, lines, *_, notes = _fit("Превысокомногорассмотрительствующий", w, h, 14)
    assert f.size == round(14 * DPI / 72)
    assert len(lines) > 1 and any("символам" in n for n in notes)
    with pytest.warns(RuntimeWarning, match="символам"):
        _render("Превысокомногорассмотрительствующий", w, h, font_size=14)

# ---------- D3 ----------
def _render(text, w, h, x=100, y=100, **st):
    el = dict(id=1, type="text", x=x, y=y, w=w, h=h, static_value=text, style_json=json.dumps(st))
    return render_card(None, [el], background={"color": "#FFFFFF"})

LONG = "Ведущий инженер-конструктор отдела перспективных разработок и испытаний изделий"

def test_overflow_keeps_all_lines_without_ellipsis():
    """При переполнении по высоте строки не отбрасываются и «…» не добавляется (обрезка — при рисовании)."""
    f, lines, ys, ws, bb, notes = _fit(LONG, 300, 100, 10, 10)
    assert f.size == round(10 * DPI / 72)
    assert any("высоте" in n for n in notes)
    assert lines and not any(l.endswith(ELLIPSIS) for l in lines)
    assert (bb[3] - bb[1]) > 100

def test_overflow_clipped_to_frame_pixels():
    """Пиксели текста не выходят за рамку; частичные глифы на краю допускаются."""
    from badge_backend import units_to_px
    w, h, x, y = 300, 100, 100, 100
    with pytest.warns(RuntimeWarning):
        a = _render(LONG, w, h, font_size=10, min_size=10)
    inv = Image.eval(a.convert("L"), lambda v: 255 - v).getbbox()
    xp, yp, wp, hp = (units_to_px(v, DPI) for v in (x, y, w, h))
    assert inv and inv[0] >= xp and inv[1] >= yp and inv[2] <= xp + wp and inv[3] <= yp + hp

def test_tiny_frame_clips_glyphs_inside():
    """Рамка ниже одной строки: глифы рисуются заданным кеглем и обрезаются, а не пропадают."""
    from badge_backend import units_to_px
    w, h, x, y = 200, 10, 100, 100
    with pytest.warns(RuntimeWarning):
        im = _render("Йурд", w, h, font_size=10)
    inv = Image.eval(im.convert("L"), lambda v: 255 - v).getbbox()
    xp, yp, wp, hp = (units_to_px(v, DPI) for v in (x, y, w, h))
    assert inv is not None
    assert inv[0] >= xp and inv[1] >= yp and inv[2] <= xp + wp and inv[3] <= yp + hp
