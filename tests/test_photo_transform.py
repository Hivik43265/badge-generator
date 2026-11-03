"""D4: трансформация фото по photo_config на фикстурах BG-Data (маркеры, аналитическая позиция)."""
import json, math
from pathlib import Path
import pytest
from PIL import Image, ImageChops
from badge_backend.render import transform_photo
from badge_backend.photo_config import PhotoConfig

FIX = Path(__file__).resolve().parents[1] / "data_tools/testdata/fixtures/photo_config"
GOLD = Path(__file__).with_name("golden")
pytestmark = pytest.mark.skipif(not (FIX / "markers.json").exists(), reason="нет фикстур D4")
MARK = json.loads((FIX / "markers.json").read_text(encoding="utf-8")) if (FIX / "markers.json").exists() else {}
FILES = ["portrait_300x400.png", "portrait_600x800.png", "landscape_400x300.png"]
W, H = 300, 400   # рамка фото демо-макета

def expected(src_size, u, v, w, h, cfg):
    """Аналитика: crop → cover×scale → поворот по часовой → центр рамки + (x, y)."""
    sw, sh = src_size
    cx, cy = min(cfg.crop_x, sw - 1), min(cfg.crop_y, sh - 1)
    cw, ch = sw - cx, sh - cy
    s = max(w / cw, h / ch) * cfg.scale
    dx, dy = (u + .5 - cx - cw / 2) * s, (v + .5 - cy - ch / 2) * s
    a = math.radians(cfg.angle)
    rx, ry = dx * math.cos(a) - dy * math.sin(a), dx * math.sin(a) + dy * math.cos(a)  # y вниз ⇒ по часовой
    return w / 2 + cfg.x + rx, h / 2 + cfg.y + ry

def near(img, x, y, color, r=2, tol=60):
    for yy in range(int(y) - r, int(y) + r + 1):
        for xx in range(int(x) - r, int(x) + r + 1):
            if 0 <= xx < img.width and 0 <= yy < img.height:
                p = img.getpixel((xx, yy))
                if p[3] > 200 and max(abs(p[i] - color[i]) for i in range(3)) <= tol: return True
    return False

CFGS = ["0;0;1.0;0;0;0", "0;0;1.5;0;0;0", "0;0;0.8;0;0;0", "20;-15;1.0;0;0;0", "0;0;1.0;40;30;0",
        "0;0;1.0;0;0;90", "0;0;1.0;0;0;-90", "0;0;1.0;0;0;30", "0;0;1.0;0;0;180", "15;10;1.3;20;40;15"]

@pytest.mark.parametrize("fname", FILES)
@pytest.mark.parametrize("cfg_s", CFGS)
def test_markers_land_where_expected(fname, cfg_s):
    src = Image.open(FIX / fname); cfg = PhotoConfig.parse(cfg_s)
    W, H = (400, 300) if src.width > src.height else (300, 400)     # рамка по ориентации исходника
    out = transform_photo(src, W, H, cfg)
    checked = 0
    for m in MARK[fname]:
        x, y = expected(src.size, m["x"], m["y"], W, H, cfg)
        if m["x"] < cfg.crop_x or m["y"] < cfg.crop_y: continue          # отрезано crop
        if not (3 <= x < W - 3 and 3 <= y < H - 3): continue             # вне рамки
        assert near(out, x, y, m["color"]), (fname, cfg_s, m["name"], round(x, 1), round(y, 1), out.getpixel((int(x), int(y))))
        checked += 1
    assert checked >= 2, (fname, cfg_s, checked)

@pytest.mark.parametrize("fname", FILES)
def test_rotation_is_clockwise_arrow_up(fname):
    """Стрелка UP при angle=90 по часовой смотрит ВПРАВО: остриё правее центра, на его высоте."""
    src = Image.open(FIX / fname); m = {k["name"]: k for k in MARK[fname]}
    sw, sh = src.size
    tip, cen = m["arrow_tip_black"], m["center_crosshair"]
    w, h = 400, 400
    out = transform_photo(src, w, h, "0;0;1.0;0;0;90")
    ex, ey = expected(src.size, tip["x"], tip["y"], w, h, PhotoConfig.parse("0;0;1.0;0;0;90"))
    cx, cy = expected(src.size, cen["x"], cen["y"], w, h, PhotoConfig.parse("0;0;1.0;0;0;90"))
    assert ex > cx + 20                        # было «вверх» → стало «вправо»
    assert near(out, ex, ey, (0, 0, 0)) and near(out, cx, cy, (0, 0, 0))
    # красный квадрат TL после поворота по часовой уходит в правый верхний угол (против часовой — был бы в левом нижнем)
    rx, ry = expected(src.size, m["TL_red_square"]["x"], m["TL_red_square"]["y"], w, h, PhotoConfig.parse("0;0;1.0;0;0;90"))
    assert rx > w / 2 and ry < h / 2

GOLDEN = [("portrait_300x400.png", "0;0;1.0;0;0;0"), ("portrait_600x800.png", "15;10;1.3;20;40;15"),
          ("landscape_400x300.png", "0;0;1.0;0;0;90"), ("landscape_400x300.png", "-20;0;1.2;60;0;-30")]

def _gname(f, c): return GOLD / f"photo_{Path(f).stem}_{c.replace(';', '_').replace('.', 'p').replace('-', 'm')}.png"

@pytest.mark.parametrize("fname,cfg_s", GOLDEN)
def test_photo_golden(fname, cfg_s):
    out = transform_photo(Image.open(FIX / fname), W, H, cfg_s)
    ref = Image.open(_gname(fname, cfg_s)).convert("RGBA")
    assert ref.size == out.size
    diff = ImageChops.difference(out, ref).convert("L")
    bad = sum(diff.point(lambda v: 255 if v > 24 else 0).histogram()[255:])
    assert bad <= out.width * out.height * 0.002, bad      # ≤0.2% пикселей с отличием >24

def make_golden():
    for f, c in GOLDEN: transform_photo(Image.open(FIX / f), W, H, c).save(_gname(f, c))

if __name__ == "__main__": make_golden()
