"""Сравнение изображений без гигантского repr байтов в выводе pytest."""


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
