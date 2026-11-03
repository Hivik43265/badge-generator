"""D44: apply_and_save_photo(size=..., target_field=...) — ресайз до размера рамки шаблона (LANCZOS)."""
from pathlib import Path
import pytest
from PIL import Image
from badge_backend import api
from badge_backend.services import photo_edit as pe
from badge_backend.services.photo_edit import PhotoSession

FIX = Path(__file__).parent / "fixtures" / "portrait_biden.jpg"

@pytest.fixture
def prj(tmp_path):
    con = api.connect(tmp_path / "p.db"); api.upsert_field(con, "pic", "Фото", data_type="image")
    api.create_element(con, "photo", 10, 10, 330, 413, field_name="pic")
    return con, tmp_path

def _sz(d, rel):
    with Image.open(d / rel) as im: return im.size

def test_target_field_resizes(prj):
    con, d = prj
    img = pe.load_photo_for_edit(FIX)
    crop = pe.detect_face_crop(img, api.photo_edit_target(con, "pic")["aspect"])
    rel = pe.apply_and_save_photo(con, str(FIX), {"crop": crop}, target_field="pic")
    assert _sz(d, rel) == (330, 413)

def test_size_kwarg_and_default(prj):
    con, d = prj
    assert _sz(d, pe.apply_and_save_photo(con, str(FIX), {"crop": (0, 0, 100, 50)}, size=(40, 40))) == (40, 40)  # aspect не тот — ровно size
    assert _sz(d, pe.apply_and_save_photo(con, str(FIX), {"crop": (0, 0, 100, 50)}, size=(40, 40), target_field="pic")) == (40, 40)
    assert _sz(d, pe.apply_and_save_photo(con, str(FIX), {"crop": (0, 0, 100, 50)})) == (100, 50)
    assert _sz(d, pe.apply_and_save_photo(con, str(FIX), {"crop": (0, 0, 100, 50)}, target_field="nope")) == (100, 50)
    with pytest.raises(ValueError): pe.apply_and_save_photo(con, str(FIX), {}, size=(0, 10))

def test_session_passes_through(prj):
    con, d = prj
    s = PhotoSession(con)
    assert _sz(d, s.apply_and_save_photo(str(FIX), {}, target_field="pic")) == (330, 413)
    assert _sz(d, s.apply_and_save_photo(str(FIX), {}, size=(20, 30))) == (20, 30)
