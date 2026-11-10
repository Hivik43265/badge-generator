"""Текст обязан помещаться в рамку w×h (реальный bbox глифов)."""
import warnings, pytest
from PIL import Image
from badge_backend import api, demo
from badge_backend.render import render_card

def _text_bbox(text, w, h, x=100, y=100, **style):
    """Рендер на прозрачном (белом) фоне без прочих элементов; bbox непустых пикселей."""
    import json
    el = dict(id=1, type="text", x=x, y=y, w=w, h=h, static_value=text, style_json=json.dumps(style))
    im = render_card(None, [el], background={"color": "#FFFFFF"})
    inv = Image.eval(im.convert("L"), lambda v: 255 - v)
    return inv.getbbox()

def _inside(bb, x, y, w, h):
    return bb is not None and bb[0] >= x and bb[1] >= y and bb[2] <= x + w and bb[3] <= y + h

CASES = [("Гость", 350, 70, {"font_size": 14}),
         ("Гость", 120, 40, {"font_size": 40}),
         ("Йурд", 300, 80, {"font_size": 30}),
         ("Йурд Ёжик щуку", 200, 120, {"font_size": 30, "align": "center", "valign": "middle"}),
         ("Йурд", 400, 100, {"font_size": 20, "valign": "bottom", "align": "right"}),
         ("Ведущий инженер-конструктор отдела перспективных разработок", 420, 160, {"font_size": 16}),
         ("Ёлка\nЙод\nщука\nДуб", 260, 220, {"font_size": 24, "line_spacing": 1.3}),
         ("Й", 60, 60, {"font_size": 60, "bold": True})]

@pytest.mark.parametrize("text,w,h,st", CASES)
def test_text_inside_frame(text, w, h, st):
    with warnings.catch_warnings():
        warnings.simplefilter("error")          # для этих случаев обрезки быть не должно
        bb = _text_bbox(text, w, h, **st)
    assert _inside(bb, 100, 100, w, h), (bb, w, h)

def test_short_text_keeps_size():
    """Короткий текст в большой рамке не уменьшается: высота глифов ~ font_size."""
    bb = _text_bbox("Йурд", 800, 300, font_size=20)       # 20 pt = 83 px
    assert bb[3] - bb[1] > 60

def test_very_long_word_clipped_with_warning():
    w, h = 150, 40
    with pytest.warns(RuntimeWarning, match="не помещается"):
        bb = _text_bbox("Превысокомногорассмотрительствующий" * 2, w, h, font_size=20, min_size=8)
    assert _inside(bb, 100, 100, w, h)

def test_min_size_respected():
    """min_size: шрифт не уменьшается ниже — длинный текст в маленькой рамке → обрезка + warning."""
    with pytest.warns(RuntimeWarning):
        bb = _text_bbox("слово " * 50, 200, 60, font_size=14, min_size=12)
    assert _inside(bb, 100, 100, 200, 60)

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

def test_demo_texts_fit_without_clipping(tmp_path):
    con = api.connect(); demo.build_demo(con); demo.make_logo(tmp_path / "demo_logo.png")
    pid = api.create_person(con, {"last_name": "Константинопольский-Щедрин", "first_name": "Йозеф",
                                  "middle_name": "Ёлкинович", "position": "Ведущий инженер " * 4, "employee_id": "Таб. № 000123"})
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        for s in ("front", "back"): api.render_card_db(con, pid, s, base_dir=tmp_path)
