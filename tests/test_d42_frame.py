"""D42 (слова Ивана: «Рамка в редакторе не должна полностью брать лицо. Учитывается размер рамки в шаблоне обязательно»):
get_photo_frame_spec + detect_face_crop (голова ≈50 %, запас над макушкой ≈10 %, шея/плечи)."""
from pathlib import Path
import pytest
from PIL import Image
from badge_backend import api
from badge_backend.services import photo_edit as pe

FIX = Path(__file__).parent / "fixtures" / "portrait_biden.jpg"

def _haar(img):
    import numpy as np
    g = np.asarray(img.convert("L")); m = max(20, min(g.shape) // 12)
    f = pe._classifier().detectMultiScale(g, scaleFactor=1.1, minNeighbors=5, minSize=(m, m))
    assert len(f) == 1
    return (float(v) for v in f[0])

def _prj(tmp_path, name, w, h):
    con = api.connect(tmp_path / f"{name}.db")
    api.upsert_field(con, "pic", "Фото", data_type="image")
    api.create_element(con, "photo", 0, 0, w * 2, h * 2, side="back", field_name="pic")   # оборот — игнор
    eid = api.create_element(con, "photo", 10, 10, w, h, field_name="pic")
    api.create_element(con, "photo", 600, 10, w + 50, h, field_name="pic", z_order=5)     # второй на лице
    return con, eid

def test_frame_spec(tmp_path):
    con, eid = _prj(tmp_path, "a", 300, 400)
    s = pe.get_photo_frame_spec(con, "pic")
    assert s["element_id"] == eid and s["side"] == "front" and abs(s["aspect"] - 0.75) < 1e-9
    assert s["width_mm"] == 25.4 and s["height_mm"] == pytest.approx(33.87, abs=0.01)
    assert (s["width_px"], s["height_px"]) == (300, 400)
    fid = con.execute("SELECT rowid FROM person_fields WHERE name='pic'").fetchone()[0]
    assert pe.get_photo_frame_spec(con, fid) == s
    assert pe.get_photo_frame_spec(con, "nope") is None
    api.upsert_field(con, "t", "Текст")
    assert pe.get_photo_frame_spec(con, "t") is None
    assert pe.get_photo_frame_spec(con, None) is None                     # нет фото-элемента без поля
    api.create_element(con, "photo", 0, 0, 413, 531)                      # 35×45 мм, photo_path
    s0 = pe.get_photo_frame_spec(con)
    assert (s0["width_mm"], s0["height_mm"]) == (34.97, 44.96) and (s0["width_px"], s0["height_px"]) == (413, 531)

def _check(img, crop, aspect):
    fx, fy, fw, fh = _haar(img)
    x, y, w, h = crop
    head_top = fy - 0.25 * fh; chin = fy + fh
    assert abs(w / h - aspect) < 0.01
    assert 0 <= x and x + w <= img.width and 0 <= y and y + h <= img.height
    assert y <= head_top                                                  # макушка внутри рамки
    share = (chin - head_top) / h; room = (head_top - y) / h
    assert 0.45 <= share <= 0.55, share
    assert 0.07 <= room <= 0.13, room
    assert abs((x + w / 2) - (fx + fw / 2)) <= 2                          # по центру
    assert y + h - chin >= 0.3 * h                                        # шея/плечи
    return share, room

def test_two_templates_different_aspects(tmp_path):
    img = Image.open(FIX); img.load()
    res = []
    for name, w, h in (("passport", 413, 531), ("wide", 500, 450)):
        con, _ = _prj(tmp_path, name, w, h)
        a = pe.get_photo_frame_spec(con, "pic")["aspect"]
        crop = pe.detect_face_crop(img, a)
        _check(img, crop, a); res.append(crop[2] / crop[3])
    assert abs(res[0] - 413 / 531) < 0.01 and abs(res[1] - 500 / 450) < 0.01 and abs(res[0] - res[1]) > 0.2

def test_shift_then_shrink():
    img = Image.open(FIX).convert("RGB")
    fx, fy, fw, fh = _haar(img)
    left = img.crop((int(fx) - 40, 0, img.width, img.height))             # лицо у левого края → сдвиг
    x, y, w, h = pe.detect_face_crop(left, 0.78)
    lfx, lfy, lfw, lfh = _haar(left)
    assert x == 0 and h == pytest.approx(2 * 1.25 * lfh, abs=2)           # размер не уменьшен
    tight = img.crop((0, 60, img.width, 460))                             # фото ниже рамки → уменьшение
    x, y, w, h = pe.detect_face_crop(tight, 0.78)
    assert h <= tight.height and y + h <= tight.height and abs(w / h - 0.78) < 0.01
