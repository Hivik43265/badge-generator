from PIL import Image

def test_photos_big_enough_and_varied(sets):
    sizes = set()
    for d in ("clean", "large"):
        for p in (sets / d / "photos").iterdir():
            with Image.open(p) as im:
                w, h = im.size
            assert w >= 300 and h >= 300 and max(w, h) >= 400
            sizes.add((w, h))
    assert {(300, 400), (600, 800), (400, 300)} <= sizes

def test_corner_markers_distinct(sets):
    with Image.open(sets / "clean/photos/p1.jpg") as im:
        im = im.convert("RGB"); w, h = im.size
        m = max(40, min(w, h) // 7)  # точки внутри фигур (квадрат, круг, треугольник, ромб)
        tl, tr, bl, br = (im.getpixel(xy) for xy in [(4, m - 6), (w - m // 2, m - 8), (4, h - 6), (w - m // 2, h - m + 10)])
    assert tl[0] > 200 and tl[1] < 60      # красный
    assert tr[1] > 150 and tr[0] < 60      # зелёный
    assert bl[2] > 200 and bl[0] < 60      # синий
    assert br[0] > 200 and br[1] > 150 and br[2] < 80  # жёлтый

def test_large_reuses_few_bases(sets):
    assert len(list((sets / "large/photos").iterdir())) == 5

def test_bad_sets_still_bad(sets):
    ph = sets / "zero_byte_and_broken/photos"
    assert (ph / "empty.jpg").stat().st_size == 0
    assert (ph / "broken.jpg").stat().st_size > 0


# --- фикстуры photo_config ---
import hashlib, json
from pathlib import Path
import make_testsets

FIX = Path(__file__).resolve().parent.parent / "testdata" / "fixtures" / "photo_config"
NAMES = ["portrait_300x400.png", "portrait_600x800.png", "landscape_400x300.png"]
SZ = {"portrait_300x400.png": (300, 400), "portrait_600x800.png": (600, 800), "landscape_400x300.png": (400, 300)}

def _h(d): return {n: hashlib.sha256((d / n).read_bytes()).hexdigest() for n in NAMES + ["markers.json"]}

def test_fixtures_mode_size_no_metadata():
    for n in NAMES:
        with Image.open(FIX / n) as im:
            assert im.mode == "RGB" and im.size == SZ[n]
            assert "transparency" not in im.info and not im.text

def test_markers_match_pixels():
    markers = json.loads((FIX / "markers.json").read_text(encoding="utf-8"))
    assert set(markers) == set(NAMES)
    for n, pts in markers.items():
        with Image.open(FIX / n) as im:
            for p in pts:
                assert list(im.getpixel((p["x"], p["y"]))) == p["color"], (n, p)
        colors = {p["name"]: tuple(p["color"]) for p in pts}
        assert colors["TL_red_square"] == (255, 0, 0) and colors["TR_green_circle"] == (0, 200, 0)
        assert colors["BL_blue_triangle"] == (0, 0, 255) and colors["BR_yellow_diamond"] == (255, 210, 0)

def test_regeneration_byte_identical(tmp_path):
    make_testsets.make_fixtures(tmp_path)
    assert _h(tmp_path) == _h(FIX)

def test_pattern_asymmetric():
    with Image.open(FIX / "portrait_300x400.png") as im:
        a = im.tobytes()
        for t in (Image.Transpose.FLIP_LEFT_RIGHT, Image.Transpose.FLIP_TOP_BOTTOM, Image.Transpose.ROTATE_180):
            assert im.transpose(t).tobytes() != a
