"""Текст рисуется заданным кеглем и обрезается по рамке w×h (реальный bbox глифов)."""
import json, warnings, pytest
from PIL import Image, ImageDraw
from badge_backend import api, demo, DPI, units_to_px
from badge_backend.render import render_card, _fit_text

def _text_bbox(text, w, h, x=100, y=100, **style):
    """Рендер на прозрачном (белом) фоне без прочих элементов; bbox непустых пикселей."""
    el = dict(id=1, type="text", x=x, y=y, w=w, h=h, static_value=text, style_json=json.dumps(style))
    im = render_card(None, [el], background={"color": "#FFFFFF"})
    inv = Image.eval(im.convert("L"), lambda v: 255 - v)
    return inv.getbbox()

def _inside(bb, x, y, w, h):
    return bb is not None and bb[0] >= x and bb[1] >= y and bb[2] <= x + w and bb[3] <= y + h

def _fit(text, w, h, pt, min_pt=8):
    d = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    return _fit_text(d, text, w, h, pt * DPI / 72, min_pt * DPI / 72, None, False, None, True, 1.0)

CASES = [("Гость", 350, 70, {"font_size": 14}),
         ("Гость", 120, 40, {"font_size": 40}),
         ("Йурд", 300, 80, {"font_size": 30}),
         ("Йурд Ёжик щуку", 200, 120, {"font_size": 30, "align": "center", "valign": "middle"}),
         ("Йурд", 400, 100, {"font_size": 20, "valign": "bottom", "align": "right"}),
         ("Ведущий инженер-конструктор отдела перспективных разработок", 420, 160, {"font_size": 16}),
         ("Ёлка\nЙод\nщука\nДуб", 260, 220, {"font_size": 24, "line_spacing": 1.3}),
         ("Й", 60, 60, {"font_size": 60, "bold": True})]

# Короткие строки в рамке, где 14/20 pt точно помещаются без обрезки.
FIT_CASES = [("Гость", 350, 70, {"font_size": 14}),
             ("Йурд", 400, 100, {"font_size": 20, "valign": "bottom", "align": "right"})]

def _frame_px(x, y, w, h):
    return tuple(units_to_px(v, DPI) for v in (x, y, w, h))

@pytest.mark.parametrize("text,w,h,st", CASES)
def test_text_inside_frame(text, w, h, st):
    """Даже при переполнении (большой кегль / длинный текст) чернила остаются в рамке."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        bb = _text_bbox(text, w, h, **st)
    assert _inside(bb, *_frame_px(100, 100, w, h)), (bb, _frame_px(100, 100, w, h))

@pytest.mark.parametrize("text,w,h,st", FIT_CASES)
def test_fitting_text_no_clip_warning(text, w, h, st):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        bb = _text_bbox(text, w, h, **st)
    assert _inside(bb, *_frame_px(100, 100, w, h))

def test_short_text_keeps_size():
    """Короткий текст в большой рамке не уменьшается: высота глифов ~ font_size."""
    bb = _text_bbox("Йурд", 800, 300, font_size=20)       # 20 pt = 83 px
    assert bb[3] - bb[1] > 60

def test_very_long_word_clipped_with_warning():
    w, h = 150, 40
    with pytest.warns(RuntimeWarning, match="не помещается"):
        bb = _text_bbox("Превысокомногорассмотрительствующий" * 2, w, h, font_size=20, min_size=8)
    assert _inside(bb, *_frame_px(100, 100, w, h))

def test_min_size_ignored_keeps_font_size():
    """min_size по-прежнему принимается в стиле, но кегль не уменьшается — обрезка при font_size."""
    f, lines, ys, ws, bb, notes = _fit("слово " * 50, 200, 60, 14, 12)
    assert f.size == round(14 * DPI / 72)
    assert notes
    with pytest.warns(RuntimeWarning):
        box = _text_bbox("слово " * 50, 200, 60, font_size=14, min_size=12)
    assert _inside(box, *_frame_px(100, 100, 200, 60))

def test_frame_at_canvas_edge():
    bb = _text_bbox("Йурд", 200, 80, x=900, y=600, font_size=30)
    assert bb is not None and bb[2] <= 1011 and bb[3] <= 638

def _overlap(a, b):
    return a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]

@pytest.mark.parametrize("side", ["front", "back"])
def test_demo_layout_no_overlaps(side):
    """В демо-макете bbox элементов не пересекаются; исключение — фоновые rect с меньшим z (подложка)."""
    con = api.connect(); demo.build_demo(con)
    els = api.list_elements(con, side); bad = []
    for i, a in enumerate(els):
        for b in els[i + 1:]:
            if not _overlap(a, b): continue
            lo, hi = sorted((a, b), key=lambda e: e["z_order"])
            if lo["type"] == "rect" and lo["z_order"] < hi["z_order"]: continue
            bad.append((a["id"], a["type"], b["id"], b["type"]))
    assert bad == []
    for e in els:
        assert e["x"] >= 0 and e["y"] >= 0 and e["x"] + e["w"] <= 856 and e["y"] + e["h"] <= 540, e

def test_demo_texts_clipped_to_element_frames(tmp_path):
    """Длинные ФИО при точном кегле могут не влезть — пиксели каждого текста остаются в его рамке."""
    con = api.connect(); demo.build_demo(con); demo.make_logo(tmp_path / "demo_logo.png")
    pid = api.create_person(con, {"last_name": "Константинопольский-Щедрин", "first_name": "Йозеф",
                                  "middle_name": "Ёлкинович", "position": "Ведущий инженер " * 4, "employee_id": "Таб. № 000123"})
    person = api.get_person(con, pid)
    for s in ("front", "back"):
        for e in api.list_elements(con, s):
            if e["type"] not in ("text", "field"): continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                im = render_card(person, [e], s, background={"color": "#FFFFFF"}, base_dir=tmp_path)
            inv = Image.eval(im.convert("L"), lambda v: 255 - v)
            bb = inv.getbbox()
            if bb is None: continue
            x, y, w, h = (units_to_px(e[k], DPI) for k in ("x", "y", "w", "h"))
            assert _inside(bb, x, y, w, h), (e["type"], e.get("field_name") or e.get("static_value"), bb, (x, y, w, h))

def test_larger_pt_gives_larger_glyphs_when_overflowing():
    """Больший pt даёт большие глифы, даже когда текст не влезает в рамку (без автоподбора)."""
    f18, _, _, _, bb18, n18 = _fit("Йурд", 80, 40, 18)
    f36, _, _, _, bb36, n36 = _fit("Йурд", 80, 40, 36)
    assert f18.size == round(18 * DPI / 72)
    assert f36.size == round(36 * DPI / 72)
    assert (bb36[3] - bb36[1]) > (bb18[3] - bb18[1])
    assert n18 and n36

def test_no_pixels_outside_padded_box():
    """Чернила не заходят в padding и не выходят за рамку элемента."""
    pad, x, y, w, h = 20, 100, 100, 300, 150
    el = dict(id=1, type="text", x=x, y=y, w=w, h=h,
              static_value="Очень длинная строка ФИО " * 8,
              style_json=json.dumps({"font_size": 40, "padding": pad}))
    with pytest.warns(RuntimeWarning):
        im = render_card(None, [el], background={"color": "#FFFFFF"})
    inv = Image.eval(im.convert("L"), lambda v: 255 - v)
    bb = inv.getbbox()
    xp, yp, wp, hp, pp = (units_to_px(v, DPI) for v in (x, y, w, h, pad))
    assert bb is not None
    assert bb[0] >= xp + pp and bb[1] >= yp + pp and bb[2] <= xp + wp - pp and bb[3] <= yp + hp - pp, (bb, (xp, yp, wp, hp, pp))

def test_long_name_keeps_font_size():
    """Длинное ФИО не уменьшает кегль: размер остаётся ровно выбранным."""
    pt = 22
    f, lines, ys, ws, bb, notes = _fit("Константинопольский-Щедрин", 200, 80, pt)
    assert f.size == round(pt * DPI / 72)
    assert notes
