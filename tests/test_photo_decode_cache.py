"""Кэш декодирования фото (путь+mtime) и рендер вида в размер рамки, без повторного полного декода."""
from pathlib import Path
from PIL import Image
from badge_backend.services import photos
from badge_backend.services import photo_edit as pe


def test_open_photo_file_cache_hit_skips_reread(tmp_path, monkeypatch):
    src = tmp_path / "cache_me.jpg"
    Image.new("RGB", (48, 32), (200, 30, 30)).save(src, quality=95)
    n = {"reads": 0}
    orig = Path.read_bytes

    def counting(self, *a, **kw):
        try:
            if self.resolve() == src.resolve():
                n["reads"] += 1
        except OSError:
            pass
        return orig(self, *a, **kw)

    monkeypatch.setattr(Path, "read_bytes", counting)
    a = photos.open_photo_file(src)
    b = photos.open_photo_file(src)
    assert n["reads"] == 1
    assert a.size == b.size == (48, 32) and a.tobytes() == b.tobytes()
    a.putpixel((0, 0), (0, 255, 0))
    c = photos.open_photo_file(src)
    assert c.getpixel((0, 0)) == (200, 30, 30)


def test_open_photo_file_cache_miss_on_mtime(tmp_path, monkeypatch):
    src = tmp_path / "changed.jpg"
    Image.new("RGB", (20, 20), (10, 20, 30)).save(src, quality=95)
    n = {"reads": 0}
    orig = Path.read_bytes

    def counting(self, *a, **kw):
        try:
            if self.resolve() == src.resolve():
                n["reads"] += 1
        except OSError:
            pass
        return orig(self, *a, **kw)

    monkeypatch.setattr(Path, "read_bytes", counting)
    photos.open_photo_file(src)
    Image.new("RGB", (20, 20), (1, 2, 3)).save(src, quality=95)
    photos.open_photo_file(src)
    assert n["reads"] == 2


def test_apply_photo_view_matches_frame_size():
    im = Image.new("RGB", (2400, 3200), (240, 240, 240))
    im.paste((180, 40, 40), (400, 200, 1400, 2000))
    out = pe.apply_photo_view(im, 150, 200, {"brightness": 12, "contrast": 6, "scale": 110,
                                             "crop": (200, 150, 900, 1200)})
    assert out.size == (150, 200)
