import json
import pytest
from PIL import Image
import badge_backend.api as api
from badge_backend.services import photo_edit as pe

def test_default_false(tmp_path):
    con = api.connect(tmp_path / "p.db")
    assert pe.get_photo_edit_defaults(con)["portrait"] is False

def test_roundtrip(tmp_path):
    con = api.connect(tmp_path / "p.db")
    r = pe.set_photo_edit_defaults(con, {"autoeffect": True, "portrait": True})
    assert r["portrait"] is True and r["autoeffect"] is True
    con.close(); con = api.connect(tmp_path / "p.db")
    d = pe.get_photo_edit_defaults(con)
    assert d["portrait"] is True and d["autoeffect"] is True
    raw = json.loads(con.execute("SELECT value FROM project_settings WHERE key='photo_edit_defaults'").fetchone()[0])
    assert raw["portrait"] is True

def test_backward_compat_old_value(tmp_path):
    con = api.connect(tmp_path / "p.db")
    old = {"brightness": 5, "contrast": 0, "scale": 100, "rotate": 0.0, "crop": None, "autoeffect": True}
    with con: con.execute("INSERT INTO project_settings(key, value) VALUES ('photo_edit_defaults', ?)", (json.dumps(old),))
    d = pe.get_photo_edit_defaults(con)
    assert d["portrait"] is False and d["autoeffect"] is True and d["brightness"] == 5

@pytest.mark.parametrize("v,exp", [("true", True), ("0", False), ("false", False), (1, True), (0, False)])
def test_bool_coercion(v, exp):
    assert pe.normalize_params({"portrait": v})["portrait"] is exp

def test_bad_string():
    with pytest.raises(ValueError):
        pe.normalize_params({"portrait": "maybe"})

def test_portrait_no_pixel_effect():
    img = Image.new("RGB", (10, 10), (100, 50, 20))
    out = pe.apply_photo_edit(img, {"portrait": True})
    assert out.tobytes() == img.tobytes() and out is not img
