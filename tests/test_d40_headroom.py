from pathlib import Path
import pytest
from PIL import Image
from badge_backend.services import photo_edit as pe

FIX = Path(__file__).parent / "fixtures" / "face_astronaut.jpg"

def _haar(img):
    import numpy as np
    g = np.asarray(img.convert("L")); m = max(20, min(g.shape) // 12)
    f = pe._classifier().detectMultiScale(g, scaleFactor=1.1, minNeighbors=5, minSize=(m, m))
    return max(f, key=lambda r: int(r[2]) * int(r[3]))

@pytest.mark.parametrize("aspect", [0.75, 1.0, 35 / 45])
def test_head_top_inside_and_ratio(aspect):
    img = Image.open(FIX); img.load()
    fx, fy, fw, fh = (int(v) for v in _haar(img))
    x, y, w, h = pe.detect_face_crop(img, aspect)
    head_top = fy - 0.3 * fh
    assert head_top - y >= 0.05 * h, (head_top, y, h)
    assert y + h >= fy + fh
    big = img.height >= (1.3 * fh) / 0.6 and img.width >= w
    if big:
        assert 0.60 <= (fy + fh - head_top) / h <= 0.70
    assert abs(w / h - aspect) < 0.02
    assert 0 <= x and x + w <= img.width and 0 <= y and y + h <= img.height

def test_upscaled_ratio():
    img = Image.open(FIX).convert("RGB"); img = img.resize((img.width * 3, img.height * 3))
    fx, fy, fw, fh = (int(v) for v in _haar(img))
    x, y, w, h = pe.detect_face_crop(img, 0.75)
    head_top = fy - 0.3 * fh
    assert y < head_top
    assert 0.60 <= (fy + fh - head_top) / h <= 0.70
