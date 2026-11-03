"""Этап 14: apply_photo_edit / detect_face_crop / умолчания проекта / apply_and_save_photo."""
from pathlib import Path
import pytest
from PIL import Image, ImageChops, ImageStat
from badge_backend import api

FACE = Path(__file__).parent / "fixtures" / "face_astronaut.jpg"

def _grad(w=60, h=40):
    im = Image.new("RGB", (w, h))
    im.putdata([(x * 255 // w, y * 255 // h, 128) for y in range(h) for x in range(w)]); return im

def _mean(im): return sum(ImageStat.Stat(im.convert("L")).mean)

def test_defaults_identity_and_not_mutated():
    src = _grad(); before = src.tobytes()
    out = api.apply_photo_edit(src, api.DEFAULT_PHOTO_EDIT)
    assert out is not src and out.tobytes() == before and api.apply_photo_edit(src, {}).tobytes() == before
    api.apply_photo_edit(src, {"brightness": 30, "contrast": -20, "scale": 150, "rotate": 33, "crop": (1, 1, 5, 5), "autoeffect": True})
    assert src.tobytes() == before and src.size == (60, 40)
    assert api.DEFAULT_PHOTO_EDIT == {"brightness": 0, "contrast": 0, "scale": 100, "rotate": 0.0, "crop": None, "autoeffect": False, "portrait": False}

def test_brightness_contrast():
    src = _grad(); m = _mean(src)
    assert _mean(api.apply_photo_edit(src, {"brightness": 40})) > m + 20
    assert _mean(api.apply_photo_edit(src, {"brightness": -40})) < m - 20
    sd = lambda im: ImageStat.Stat(im.convert("L")).stddev[0]
    assert sd(api.apply_photo_edit(src, {"contrast": 50})) > sd(src) * 1.2
    assert sd(api.apply_photo_edit(src, {"contrast": -50})) < sd(src) * 0.7

def test_clamping_and_types():
    from badge_backend.services.photo_edit import normalize_params
    p = normalize_params({"brightness": 999, "contrast": "-80", "scale": 1, "rotate": 500, "autoeffect": 1, "crop": [1.4, 2, 3, 4], "junk": 5})
    assert p == {"brightness": 50, "contrast": -50, "scale": 10, "rotate": 180.0, "crop": (1, 2, 3, 4), "autoeffect": True, "portrait": False}
    assert normalize_params({"scale": 9999})["scale"] == 400
    with pytest.raises(ValueError): normalize_params({"brightness": "abc"})
    with pytest.raises(ValueError): normalize_params({"crop": (0, 0, 0, 5)})
    with pytest.raises(ValueError): api.apply_photo_edit(_grad(), {"crop": (500, 500, 5, 5)})

def test_scale():
    assert api.apply_photo_edit(_grad(), {"scale": 50}).size == (30, 20)
    assert api.apply_photo_edit(_grad(), {"scale": 400}).size == (240, 160)

def test_rotate_clockwise():
    im = Image.new("RGB", (40, 20), "white"); im.paste((255, 0, 0), (30, 0, 40, 10))   # красный — справа сверху
    out = api.apply_photo_edit(im, {"rotate": 90})
    assert out.size == (20, 40)
    # по часовой: правый верхний угол уходит в правый нижний
    assert out.getpixel((15, 35))[0] > 200 and out.getpixel((15, 35))[1] < 60
    assert out.getpixel((5, 5)) == (255, 255, 255)
    ccw = api.apply_photo_edit(im, {"rotate": -90})
    assert ccw.getpixel((5, 5))[1] < 60     # против часовой: в левый верхний

def test_crop_after_transform():
    im = Image.new("RGB", (40, 20), "white"); im.paste((255, 0, 0), (30, 0, 40, 10))
    out = api.apply_photo_edit(im, {"scale": 200, "rotate": 90, "crop": (0, 60, 40, 20)})   # координаты после scale+rotate (40x80)
    assert out.size == (40, 20) and out.getpixel((30, 10))[1] < 60
    assert api.apply_photo_edit(im, {"crop": (30, 15, 100, 100)}).size == (10, 5)   # обрезка по границам

def test_autoeffect_and_manual_on_top():
    dull = Image.new("RGB", (50, 50)); dull.putdata([(60 + (i % 50) // 5,) * 3 for i in range(2500)])   # тусклое, узкий диапазон
    a = api.apply_photo_edit(dull, {"autoeffect": True})
    ex = a.convert("L").getextrema()
    assert ex[1] - ex[0] > 150 and abs(_mean(a) - 128) < 40
    assert _mean(api.apply_photo_edit(dull, {"autoeffect": True, "brightness": 40})) > _mean(a) + 15

def test_rgba_keeps_alpha():
    im = Image.new("RGBA", (20, 20), (100, 100, 100, 0)); im.paste((200, 0, 0, 255), (0, 0, 10, 10))
    out = api.apply_photo_edit(im, {"brightness": 20, "rotate": 45})
    assert out.mode == "RGBA" and out.getpixel((0, 0))[3] == 0

def test_detect_face_crop():
    img = Image.open(FACE); img.load()
    for aspect in (3 / 4, 1.0, 0.8):
        r = api.detect_face_crop(img, aspect)
        assert r is not None
        x, y, w, h = r
        assert 0 <= x and 0 <= y and x + w <= img.width and y + h <= img.height
        assert abs(w / h - aspect) < 0.03
    # лицо по центру по горизонтали; маленькое фото → рамка уменьшена, макушка (Haar−0.25·fh) внутри (D42)
    import cv2, numpy as np
    from badge_backend.services.photo_edit import _classifier
    fx, fy, fw, fh = max(_classifier().detectMultiScale(np.asarray(img.convert("L")), 1.1, 5, minSize=(20, 20)), key=lambda f: f[2] * f[3])
    x, y, w, h = api.detect_face_crop(img, 0.75)
    assert abs((x + w / 2) - (fx + fw / 2)) <= 2 and y <= fy - 0.25 * fh

def test_detect_face_crop_clamps_big_frame():
    img = Image.open(FACE).crop((40, 10, 140, 90))   # лицо почти во весь кадр → кадр уменьшен и вписан
    r = api.detect_face_crop(img, 0.75)
    if r is not None:
        x, y, w, h = r
        assert x >= 0 and y >= 0 and x + w <= img.width and y + h <= img.height and abs(w / h - 0.75) < 0.05

def test_no_face():
    assert api.detect_face_crop(_grad(200, 200), 0.75) is None
    with pytest.raises(ValueError): api.detect_face_crop(_grad(), 0)

def test_project_defaults(tmp_path):
    con = api.connect(tmp_path / "p.db")
    assert api.get_photo_edit_defaults(con) == api.DEFAULT_PHOTO_EDIT
    saved = api.set_photo_edit_defaults(con, {"brightness": 10, "contrast": 99, "crop": (1, 1, 2, 2), "autoeffect": True})
    assert saved["contrast"] == 50 and saved["crop"] is None
    con.close(); con = api.connect(tmp_path / "p.db")
    assert api.get_photo_edit_defaults(con) == {**api.DEFAULT_PHOTO_EDIT, "brightness": 10, "contrast": 50, "autoeffect": True}

def test_apply_and_save_photo(tmp_path):
    con = api.connect(tmp_path / "p.db")
    api.upsert_field(con, "pic", "Снимок", data_type="image"); api.upsert_field(con, "name", "Имя")
    src = tmp_path / "orig.jpg"; _grad(80, 60).save(src, quality=95); raw = src.read_bytes()
    pid = api.create_person(con, {"name": "А"})
    rel = api.apply_and_save_photo(con, "orig.jpg", {"scale": 50, "rotate": 90}, person_id=pid)
    assert src.read_bytes() == raw and rel.startswith("photos/") and rel != "orig.jpg"
    assert Image.open(tmp_path / rel).size == (30, 40) and api.get_person(con, pid)["photo_path"] == rel
    rel2 = api.apply_and_save_photo(con, src, {"brightness": 10}, person_id=pid, field_name="pic")
    p = api.get_person(con, pid)
    assert p["fields"]["pic"] == rel2 and p["photo_path"] == rel and rel2 != rel and src.read_bytes() == raw
    assert api.apply_and_save_photo(con, src, None).startswith("photos/")
    n = len(list((tmp_path / "photos").iterdir()))
    with pytest.raises(ValueError): api.apply_and_save_photo(con, src, {}, person_id=pid, field_name="name")
    with pytest.raises(ValueError): api.apply_and_save_photo(con, src, {}, person_id=999)
    with pytest.raises(ValueError): api.apply_and_save_photo(con, "nope.jpg", {}, person_id=pid)
    assert len(list((tmp_path / "photos").iterdir())) == n

def test_cascade_path_frozen(tmp_path, monkeypatch):
    import sys
    from badge_backend.services import photo_edit
    (tmp_path / "cv2" / "data").mkdir(parents=True); (tmp_path / "cv2" / "data" / photo_edit.CASCADE).write_text("x")
    monkeypatch.setattr(sys, "frozen", True, raising=False); monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert photo_edit.cascade_path() == str(tmp_path / "cv2" / "data" / photo_edit.CASCADE)
    monkeypatch.setattr(sys, "frozen", False)
    assert Path(photo_edit.cascade_path()).is_file()

def test_load_photo_for_edit_exif(tmp_path):
    im = Image.new("RGB", (40, 20), "white"); im.paste((255, 0, 0), (0, 0, 10, 10))
    ex = Image.Exif(); ex[0x0112] = 6   # Orientation=6: показать с поворотом на 90° по часовой
    im.save(tmp_path / "rot.jpg", exif=ex, quality=95)
    a = api.load_photo_for_edit("rot.jpg", tmp_path)
    assert a.size == (20, 40) and a.mode == "RGB" and a.getpixel((15, 5))[1] < 80   # красный угол → правый верхний
    con = api.connect(tmp_path / "p.db")
    rel = api.apply_and_save_photo(con, "rot.jpg", None)
    b = Image.open(tmp_path / rel)
    assert b.size == a.size and b.getpixel((15, 5))[1] < 80
    Image.new("P", (5, 5)).save(tmp_path / "p.png"); assert api.load_photo_for_edit(tmp_path / "p.png").mode == "RGB"
    with pytest.raises(ValueError): api.load_photo_for_edit("nope.jpg", tmp_path)
