"""D42 (слова Ивана: «Рамка в редакторе не должна полностью брать лицо. Учитывается размер рамки в шаблоне обязательно»):
get_photo_frame_spec + detect_face_crop (голова ≈50 %, запас над макушкой ≈10 %, шея/плечи)."""
from pathlib import Path
import pytest
from PIL import Image
from badge_backend import api, units_to_px, units_to_mm
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
    assert s["width_mm"] == pytest.approx(units_to_mm(300), abs=0.01)
    assert s["height_mm"] == pytest.approx(units_to_mm(400), abs=0.01)
    assert (s["width_px"], s["height_px"]) == (units_to_px(300), units_to_px(400))
    fid = con.execute("SELECT rowid FROM person_fields WHERE name='pic'").fetchone()[0]
    assert pe.get_photo_frame_spec(con, fid) == s
    assert pe.get_photo_frame_spec(con, "nope") is None
    api.upsert_field(con, "t", "Текст")
    assert pe.get_photo_frame_spec(con, "t") is None
    s_first = pe.get_photo_frame_spec(con)                                # без field — первый фото активного шаблона
    assert s_first["element_id"] == eid and s_first["aspect"] == s["aspect"]
    eid2 = api.create_element(con, "photo", 0, 0, 413, 531)               # id больше eid → не первый
    assert pe.get_photo_frame_spec(con)["element_id"] == eid               # без предпочтения поля «Фото»
    s0 = pe.get_photo_frame_spec(con, element_id=eid2)
    assert (s0["width_mm"], s0["height_mm"]) == (
        pytest.approx(units_to_mm(413), abs=0.01), pytest.approx(units_to_mm(531), abs=0.01)
    ) and (s0["width_px"], s0["height_px"]) == (units_to_px(413), units_to_px(531))
    assert s0["element_id"] == eid2

def _check(img, crop, aspect):
    fx, fy, fw, fh = _haar(img)
    x, y, w, h = crop
    head_top = fy - pe.HEAD_TOP * fh; chin = fy + fh
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
    left = img.crop((int(fx) - 80, 0, img.width, img.height))             # лицо у левого края → сдвиг
    x, y, w, h = pe.detect_face_crop(left, 0.78)
    lfx, lfy, lfw, lfh = _haar(left)
    assert x == 0 and h == pytest.approx((1 + pe.HEAD_TOP) / pe.HEAD_SHARE * lfh, abs=2)  # размер не уменьшен
    tight = img.crop((0, 60, img.width, 460))                             # фото ниже рамки → уменьшение
    x, y, w, h = pe.detect_face_crop(tight, 0.78)
    assert h <= tight.height and y + h <= tight.height and abs(w / h - 0.78) < 0.01

def test_photo_edit_target(tmp_path):
    con, eid = _prj(tmp_path, "t", 413, 531)
    t = api.photo_edit_target(con, "pic")
    spec = pe.get_photo_frame_spec(con, "pic")
    assert t == {**spec, "size": (spec["width_px"], spec["height_px"])} and t["element_id"] == eid
    assert pe.photo_edit_target(con, "nope") is None


def test_frame_spec_element_id(tmp_path):
    con, eid = _prj(tmp_path, "e", 200, 100)
    s = pe.get_photo_frame_spec(con, element_id=eid)
    assert s["element_id"] == eid and abs(s["aspect"] - 2.0) < 1e-9
    assert api.photo_edit_target(con, element_id=eid)["size"] == (s["width_px"], s["height_px"])
    from badge_backend.services import templates as T
    b = T.create_template(con, "Другой"); T.set_active_template(con, b)
    with pytest.raises(ValueError, match="не на активном шаблоне"):
        pe.get_photo_frame_spec(con, element_id=eid)
    T.set_active_template(con, T.list_templates(con)[0]["id"])
    text = api.create_element(con, "text", 0, 0, 10, 10, static_value="x")
    with pytest.raises(ValueError, match="тип"):
        pe.get_photo_frame_spec(con, element_id=text)
    with pytest.raises(ValueError, match="нет элемента"):
        pe.get_photo_frame_spec(con, element_id=999999)

def test_frame_spec_no_foto_preference(tmp_path):
    """Без element_id/field — первый фото-элемент (front, z_order, id), не поле «Фото»."""
    con = api.connect(tmp_path / "pref.db")
    api.upsert_field(con, "pic", "Снимок", data_type="image")
    a = api.create_element(con, "photo", 0, 0, 80, 80, field_name="pic")     # первый по id
    api.create_element(con, "photo", 0, 0, 200, 50)                          # авто-«Фото», больше id
    s = pe.get_photo_frame_spec(con)
    assert s["element_id"] == a and abs(s["aspect"] - 1.0) < 1e-9

ASTRO = Path(__file__).parent / "fixtures" / "face_astronaut.jpg"

def test_portrait_astronaut_crown_and_tone():
    """Портрет на face_astronaut: макушка (верх Haar − 0.5·fh) внутри рамки, голова 40–60 % высоты;
    яркость и контраст не меняются."""
    img = Image.open(ASTRO); img.load()
    prev = {"brightness": 18, "contrast": 8, "scale": 110}
    p = pe.portrait_params(img, 0.75, prev)
    assert p is not None and p["portrait"] is True
    assert p["brightness"] == 18 and p["contrast"] == 8 and p["scale"] == 110
    base = pe.apply_photo_edit(img, {**prev, "crop": None, "autoeffect": False, "brightness": 0, "contrast": 0})
    fx, fy, fw, fh = _haar(base)
    x, y, w, h = p["crop"]
    assert 0 <= x and x + w <= base.width and 0 <= y and y + h <= base.height
    crown, chin = fy - 0.5 * fh, fy + fh
    assert y <= crown
    share = (chin - crown) / h
    assert 0.40 <= share <= 0.60, share

