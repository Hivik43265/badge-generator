"""D43: discard_photo / PhotoSession — отмена формы записи удаляет только новые файлы photos/ без ссылок."""
import io
from PIL import Image
from badge_backend import api
from badge_backend.services.photo_edit import PhotoSession, discard_photo

def _png():
    b = io.BytesIO(); Image.new("RGB", (8, 8), "red").save(b, "PNG"); return b.getvalue()

def test_session_discard(tmp_path):
    con = api.connect(tmp_path / "p.db"); api.upsert_field(con, "pic", "Фото", data_type="image")
    src = tmp_path / "src.png"; src.write_bytes(_png())
    keep = api.save_photo(con, _png())
    pid = api.create_person(con, {"pic": keep})
    s = PhotoSession(con)
    a = s.save_photo(_png()); b = s.apply_and_save_photo(str(src), {"brightness": 10})
    c = s.track(keep)                                             # уже есть ссылка → не удаляется
    s.track(str(src))                                             # исходник вне photos/ → не удаляется
    s.track("photos/../src.png"); s.track("photos/missing.jpg")
    assert sorted(s.discard()) == sorted([a, b])
    assert not (tmp_path / a).exists() and not (tmp_path / b).exists()
    assert (tmp_path / keep).exists() and src.exists() and s.created == []

def test_photo_path_reference_and_commit(tmp_path):
    con = api.connect(tmp_path / "p.db")
    s = PhotoSession(con)
    a = s.save_photo(_png()); b = s.save_photo(_png())
    api.create_person(con, {}, photo_path=b)
    assert s.commit(discard_unreferenced=True) == [a] and (tmp_path / b).exists()
    c = api.save_photo(con, _png())
    assert discard_photo(con, c) == [c] and discard_photo(con, [b, None, ""]) == []
