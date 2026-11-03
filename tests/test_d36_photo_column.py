"""D36: колонка фото → image-поле, если оно есть в проекте, иначе persons.photo_path."""
import pytest
from badge_backend import api
from badge_backend.services.headers import PHOTO_TARGET

def _csv(p, text): p.write_text(text, encoding="utf-8"); return p

@pytest.fixture
def ph(tmp_path):
    from badge_backend import demo
    d = tmp_path / "ph"; d.mkdir(); demo.make_photo(d / "a.jpg"); return d

@pytest.mark.parametrize("head", ["Фото", "photo", "Путь к фото"])
def test_no_image_field_goes_to_photo_path(tmp_path, ph, head):
    con = api.connect(); api.upsert_field(con, "last_name", "Фамилия")
    assert api.auto_match(["Фамилия", head], fields=con) == ["last_name", PHOTO_TARGET]
    rep = api.import_rows(con, api.open_source(_csv(tmp_path / "a.csv", f"Фамилия;{head}\nИванов;a.jpg\n"))[0], photo_dir=ph)
    p = api.list_persons(con)[0]
    assert rep.added == 1 and p["photo_path"] == "a.jpg" and p["fields"] == {"last_name": "Иванов"}
    rep = api.import_file(con, _csv(tmp_path / "b.csv", f"Фамилия;{head}\nПетров;a.jpg\n"), photo_dir=ph)
    assert api.list_persons(con)[1]["photo_path"] == "a.jpg"

def test_image_field_receives_photo_column(tmp_path, ph):
    con = api.connect(); api.upsert_field(con, "last_name", "Фамилия"); api.upsert_field(con, "pic", "Снимок", data_type="image")
    assert api.auto_match(["Фамилия", "Фото"], fields=con) == ["last_name", "pic"]
    rep = api.import_rows(con, api.open_source(_csv(tmp_path / "a.csv", "Фамилия;Фото\nИванов;a.jpg\n"))[0], photo_dir=ph)
    p = api.list_persons(con)[0]
    assert rep.added == 1 and p["photo_path"] is None and p["fields"]["pic"] == "a.jpg"
    api.import_file(con, _csv(tmp_path / "b.csv", "Фамилия;Фото\nПетров;a.jpg\n"), photo_dir=ph)
    assert api.list_persons(con)[1]["fields"]["pic"] == "a.jpg"

@pytest.mark.parametrize("token", ["photo_path", "photo", "__photo__"])
@pytest.mark.parametrize("with_img", [False, True])
def test_manual_mapping_token(tmp_path, ph, token, with_img):
    con = api.connect(); api.upsert_field(con, "last_name", "Фамилия")
    if with_img: api.upsert_field(con, "pic", "Снимок", data_type="image")
    m = {"Картинка": token}
    assert api.auto_match(["Фамилия", "Картинка"], m, fields=con) == ["last_name", "pic" if with_img else "photo_path"]
    api.import_rows(con, api.open_source(_csv(tmp_path / "a.csv", "Фамилия;Картинка\nИванов;a.jpg\n"))[0], m, photo_dir=ph)
    p = api.list_persons(con)[0]
    assert (p["fields"].get("pic"), p["photo_path"]) == (("a.jpg", None) if with_img else (None, "a.jpg"))
