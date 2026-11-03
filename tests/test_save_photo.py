import io
import pytest
from PIL import Image
from badge_backend import api

def _png():
    b = io.BytesIO(); Image.new("RGB", (20, 30), "red").save(b, "PNG"); return b.getvalue()

def _jpg():
    b = io.BytesIO(); Image.new("RGB", (20, 30), "blue").save(b, "JPEG"); return b.getvalue()

def test_save_into_project_photos_and_set_person(tmp_path):
    con = api.connect(tmp_path / "project.db")
    pid = api.create_person(con, {"last_name": "А"})
    rel = api.save_photo(con, _jpg(), person_id=pid)
    assert rel.startswith("photos/p%d_" % pid) and rel.endswith(".jpg")
    assert (tmp_path / rel).read_bytes() == _jpg()
    assert api.get_person(con, pid)["photo_path"] == rel
    rel2 = api.save_photo(con, _png(), ext=".PNG")
    assert rel2 != rel and rel2.endswith(".png") and (tmp_path / rel2).is_file()
    assert api.project_base_dir(con) == tmp_path.resolve()

@pytest.mark.parametrize("data", [b"", None, b"not an image", _png()[:40]])
def test_reject_empty_broken(tmp_path, data):
    con = api.connect(tmp_path / "p.db")
    with pytest.raises(ValueError): api.save_photo(con, data)
    assert not list((tmp_path / "photos").glob("*")) if (tmp_path / "photos").exists() else True

def test_unknown_person_leaves_no_file_and_base_dir_override(tmp_path):
    con = api.connect()
    with pytest.raises(ValueError): api.save_photo(con, _png(), person_id=999, base_dir=tmp_path)
    assert list((tmp_path / "photos").glob("*")) == []
    rel = api.save_photo(con, _png(), base_dir=tmp_path); assert (tmp_path / rel).is_file()
