"""Сравнение изображений без гигантского repr байтов в выводе pytest."""
from pathlib import Path

from PIL import ImageChops

GOLDEN_ACTUAL = Path(__file__).resolve().parent / "_golden_actual"


def save_golden_actual(name, im):
    """Сохранить фактический рендер при расхождении с эталоном (для артефакта CI)."""
    GOLDEN_ACTUAL.mkdir(parents=True, exist_ok=True)
    im.save(GOLDEN_ACTUAL / f"{name}.png")


def assert_matches_golden(im, ref, name):
    """Попиксельное сравнение с эталоном; при расхождении пишет tests/_golden_actual/<name>.png."""
    diff = ImageChops.difference(im.convert("RGB"), ref.convert("RGB"))
    if diff.getbbox() is not None:
        save_golden_actual(name, im)
    assert diff.getbbox() is None


def assert_same_pixels(a, b):
    assert a.size == b.size and a.mode == b.mode, ((a.size, a.mode), (b.size, b.mode))
    ba, bb = a.tobytes(), b.tobytes()
    if ba == bb:
        return
    n = min(len(ba), len(bb))
    i = next((k for k in range(n) if ba[k] != bb[k]), n)
    raise AssertionError(
        f"pixels differ: len {len(ba)} vs {len(bb)}, first_diff={i}, "
        f"a[{i}:{i+3}]={ba[i:i+3]!r} b[{i}:{i+3}]={bb[i:i+3]!r}"
    )
