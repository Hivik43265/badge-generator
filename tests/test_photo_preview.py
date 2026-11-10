"""load_photo_for_preview и потокобезопасность кэша open_photo_file."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from PIL import Image
from badge_backend import api
from badge_backend.services import photos
from badge_backend.services.photo_edit import DETECT_MAX_SIDE


def _save(path, size, color=(200, 30, 30)):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, quality=95)
    return path


def test_preview_downscales_large_image_keeps_aspect(tmp_path):
    src = _save(tmp_path / "wide.jpg", (1600, 800), (10, 20, 30))
    out = api.load_photo_for_preview(src, max_side=800)
    assert out.size == (800, 400)
    src2 = _save(tmp_path / "tall.jpg", (600, 1200), (11, 22, 33))
    out2 = api.load_photo_for_preview(src2, max_side=400)
    assert out2.size == (200, 400)
    assert max(out2.size) == 400


def test_preview_does_not_upscale_small_image(tmp_path):
    src = _save(tmp_path / "small.jpg", (100, 50), (40, 50, 60))
    out = api.load_photo_for_preview(src)
    assert out.size == (100, 50)
    out2 = api.load_photo_for_preview(src, max_side=DETECT_MAX_SIDE)
    assert out2.size == (100, 50)


def test_preview_is_distinct_from_cache(tmp_path):
    src = _save(tmp_path / "cache.jpg", (200, 100), (200, 30, 30))
    out = api.load_photo_for_preview(src, max_side=800)
    key = photos._photo_cache_key(src)
    assert key in photos._photo_cache
    cached = photos._photo_cache[key]
    assert out is not cached
    assert out.size == cached.size == (200, 100)
    out.putpixel((0, 0), (0, 255, 0))
    assert cached.getpixel((0, 0)) == (200, 30, 30)
    again = photos.open_photo_file(src)
    assert again is not out and again is not cached
    assert again.getpixel((0, 0)) == (200, 30, 30)


def test_open_photo_file_concurrent_cache_bounded(tmp_path):
    files = [_save(tmp_path / f"p{i}.jpg", (32, 24), (i * 20, 40, 60)) for i in range(6)]
    with photos._photo_cache_lock:
        photos._photo_cache.clear()
    def load(path):
        im = photos.open_photo_file(path)
        assert im.size == (32, 24)
        return im.size
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(load, files[i % len(files)]) for i in range(48)]
        results = [f.result() for f in futs]
    assert results == [(32, 24)] * 48
    with photos._photo_cache_lock:
        n = len(photos._photo_cache)
    assert n <= photos._PHOTO_CACHE_MAX
    assert n <= 4
