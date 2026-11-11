import warnings, logging
from pathlib import Path
import pytest
from PIL import Image, ImageChops
from badge_backend import api, demo, CARD_W_PX, CARD_H_PX
from badge_backend.render import render_card, transform_photo, find_font_path
from tests.image_assert import save_golden_actual
GOLDEN = Path(__file__).parent / "golden"

def quad_img(w=200, h=200):
    """Четыре цветных квадранта: R G / B Y."""
    im = Image.new("RGB", (w, h))
    for (x, y), c in {(0, 0): (255, 0, 0), (1, 0): (0, 255, 0), (0, 1): (0, 0, 255), (1, 1): (255, 255, 0)}.items():
        im.paste(c, (x * w // 2, y * h // 2, (x + 1) * w // 2, (y + 1) * h // 2))
    return im

def near(px, c, tol=40): return all(abs(a - b) <= tol for a, b in zip(px[:3], c))

def test_size_and_mode_both_sides(demo_db):
    c, ids, d = demo_db
    for s in ("front", "back"):
        im = api.render_card_db(c, ids[0], s, base_dir=d)
        assert im.size == (1011, 638) == (CARD_W_PX, CARD_H_PX) and im.mode == "RGB"

def test_empty_template_and_no_person():
    im = render_card(None, [], "front"); assert im.size == (1011, 638) and im.getpixel((5, 5)) == (255, 255, 255)

def test_bad_side():
    with pytest.raises(ValueError): render_card(None, [], "top")

def test_z_order_and_side_filter():
    els = [dict(type="rect", x=0, y=0, w=100, h=100, side="front", z_order=2, style_json='{"fill":"#00FF00"}'),
           dict(type="rect", x=0, y=0, w=100, h=100, side="front", z_order=1, style_json='{"fill":"#FF0000"}'),
           dict(type="rect", x=0, y=0, w=100, h=100, side="back", z_order=9, style_json='{"fill":"#0000FF"}')]
    assert render_card(None, els, "front").getpixel((50, 50)) == (0, 255, 0)
    assert render_card(None, els, "back").getpixel((50, 50)) == (0, 0, 255)

def test_background_color_and_image(tmp_path):
    assert render_card(None, [], "front", {"color": "#102030"}).getpixel((500, 300)) == (16, 32, 48)
    Image.new("RGB", (10, 10), (200, 10, 10)).save(tmp_path / "bg.png")
    im = render_card(None, [], "front", {"color": "#FFFFFF", "image_path": "bg.png"}, base_dir=tmp_path)
    assert near(im.getpixel((0, 0)), (200, 10, 10), 2) and near(im.getpixel((1010, 637)), (200, 10, 10), 2)

def test_field_and_cyrillic_font():
    assert find_font_path() and find_font_path().lower().endswith(".ttf")
    el = dict(type="field", x=0, y=0, w=856, h=540, field_name="last_name", style_json='{"font_size":40}')
    blank = render_card({"fields_json": "{}"}, [el]); full = render_card({"fields_json": '{"last_name":"Ёжиков"}'}, [el])
    assert ImageChops.difference(blank, full).getbbox() is not None
    assert ImageChops.difference(blank, render_card(None, [])).getbbox() is None  # пустое значение — ничего

@pytest.mark.parametrize("align,side", [("left", "l"), ("right", "r")])
def test_align(align, side):
    el = dict(type="text", x=0, y=0, w=1000, h=200, static_value="Тест", style_json=f'{{"font_size":20,"align":"{align}"}}')
    bb = ImageChops.difference(render_card(None, [el]), render_card(None, [])).getbbox()
    assert (bb[0] < 50) if side == "l" else (bb[2] > 950)

def test_text_clipped_stays_in_box():
    """Длинный текст при большом кегле обрезается по рамке, без автоуменьшения."""
    from badge_backend import units_to_px, DPI
    el = dict(type="text", x=100, y=100, w=200, h=60, static_value="Очень длинная строка " * 10,
              style_json='{"font_size":40}')
    with pytest.warns(RuntimeWarning, match="обрезан"):
        im = render_card(None, [el])
    bb = ImageChops.difference(im, render_card(None, [])).getbbox()
    xp, yp, wp, hp = (units_to_px(v, DPI) for v in (100, 100, 200, 60))
    assert bb and bb[0] >= xp and bb[1] >= yp and bb[2] <= xp + wp and bb[3] <= yp + hp

def test_rect_border_radius():
    from badge_backend import units_to_px
    el = dict(type="rect", x=100, y=100, w=200, h=200,
              style_json='{"fill":"#FF0000","border_color":"#000000","border_width":10,"radius_mm":3}')
    im = render_card(None, [el])
    cx, cy = units_to_px(200), units_to_px(200)
    top = units_to_px(100)
    assert im.getpixel((cx, cy)) == (255, 0, 0) and im.getpixel((cx, top + 8)) == (0, 0, 0)
    assert im.getpixel((top + 1, top + 1)) == (255, 255, 255)  # скруглённый угол

# --- трансформация фото на синтетике ---
def test_photo_default_cover_fills_frame():
    t = transform_photo(quad_img(), 100, 100, "0;0;1.0;0;0;0")
    assert t.getchannel("A").getextrema() == (255, 255)
    assert near(t.getpixel((10, 10)), (255, 0, 0)) and near(t.getpixel((90, 90)), (255, 255, 0))

def test_photo_crop_xy_px():
    t = transform_photo(quad_img(), 100, 100, "0;0;1.0;100;100;0")   # только жёлтый квадрант
    assert all(near(t.getpixel(p), (255, 255, 0)) for p in [(5, 5), (50, 50), (95, 95)])

def test_photo_scale_zoom_center():
    t = transform_photo(quad_img(), 100, 100, "0;0;4.0;0;0;0")
    assert near(t.getpixel((30, 30)), (255, 0, 0)) and near(t.getpixel((70, 70)), (255, 255, 0))
    t = transform_photo(quad_img(), 100, 100, "0;0;0.5;0;0;0")       # меньше рамки → прозрачные края
    assert t.getpixel((2, 2))[3] == 0 and t.getpixel((50, 50))[3] == 255

def test_photo_shift_xy():
    t = transform_photo(quad_img(), 100, 100, "30;0;1.0;0;0;0")       # вправо на 30 px
    assert t.getpixel((10, 50))[3] == 0 and near(t.getpixel((40, 10)), (255, 0, 0))
    t = transform_photo(quad_img(), 100, 100, "0;30;1.0;0;0;0")
    assert t.getpixel((50, 10))[3] == 0

def test_photo_rotation_clockwise():
    t = transform_photo(quad_img(), 100, 100, "0;0;1.0;0;0;90")      # по часовой: R→вправо-вверх
    assert near(t.getpixel((80, 20)), (255, 0, 0)) and near(t.getpixel((20, 20)), (0, 0, 255))

def test_photo_invalid_config_warns_and_defaults():
    with pytest.warns(RuntimeWarning):
        t = transform_photo(quad_img(), 100, 100, "bad")
    assert near(t.getpixel((10, 10)), (255, 0, 0))

def test_photo_in_card_and_missing_placeholder(tmp_path):
    quad_img().save(tmp_path / "q.png")
    el = dict(type="photo", x=0, y=0, w=100, h=100)
    im = render_card({"photo_path": "q.png", "photo_config": "0;0;1.0;0;0;0"}, [el], base_dir=tmp_path)
    assert near(im.getpixel((10, 10)), (255, 0, 0))
    for p in ({"photo_path": "missing.jpg"}, {"photo_path": None}, None):
        ph = render_card(p, [el], base_dir=tmp_path)
        assert ph.size == (1011, 638) and ph.getpixel((5, 5)) != (255, 255, 255)
    (tmp_path / "broken.jpg").write_bytes(b"xx")
    assert render_card({"photo_path": "broken.jpg"}, [el], base_dir=tmp_path).size == (1011, 638)

def test_qr_barcode_now_rendered():
    """Этап 10: qr и barcode входят в v1 и рисуются (раньше пропускались)."""
    els = [dict(id=1, type="qr", x=0, y=0, w=200, h=200, static_value="X"),
           dict(id=2, type="barcode", x=250, y=0, w=500, h=150, static_value="123")]
    im = render_card(None, els)
    assert ImageChops.difference(im, render_card(None, [])).getbbox() is not None

def test_preview(demo_db):
    c, ids, d = demo_db
    assert api.render_preview(c, ids[0], "front", 0.5, base_dir=d).size == (506, 319)

GOLD_CASES = {"front_full": (0, "front"), "front_no_photo": (1, "front"), "back": (0, "back")}

@pytest.mark.parametrize("name", list(GOLD_CASES))
def test_golden(demo_db, name):
    c, ids, d = demo_db; i, s = GOLD_CASES[name]
    im = api.render_card_db(c, ids[i], s, base_dir=d)
    ref = Image.open(GOLDEN / f"{name}.png").convert("RGB")
    assert ref.size == im.size == (1011, 638)
    diff = ImageChops.difference(im, ref).convert("L")
    bad = sum(diff.histogram()[33:])
    if not (bad < 0.002 * 1011 * 638):
        save_golden_actual(name, im)
    assert bad < 0.002 * 1011 * 638, f"{name}: {bad} px отличаются"
