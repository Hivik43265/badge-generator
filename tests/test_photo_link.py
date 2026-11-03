"""Вариант (a): photo-элемент ↔ image-поле; resolve_photo_path — единое правило фото."""
import pytest
from PIL import Image
from badge_backend import api
from badge_backend.render import render_card_db

def _img(path, color):
    path.parent.mkdir(parents=True, exist_ok=True); Image.new("RGB", (40, 40), color).save(path); return path

@pytest.fixture
def prj(tmp_path):
    con = api.connect(tmp_path / "project.db")
    api.upsert_field(con, "name", "Имя"); api.upsert_field(con, "pic", "Снимок", data_type="image")
    return con, tmp_path

def test_link_photo_to_image_and_unlink(prj):
    con, _ = prj
    ph = api.create_element(con, "photo", 0, 0, 100, 100)
    assert api.link_field(con, ph, "pic") is True
    links = api.list_field_links(con)
    assert [(l["element_id"], l["type"]) for l in links["pic"]] == [(ph, "photo")]
    assert api.unlink_field(con, ph) is True
    e = [x for x in api.list_elements(con) if x["id"] == ph][0]
    assert e["type"] == "photo" and e["field_name"] is None and "pic" not in api.list_field_links(con)

@pytest.mark.parametrize("t", ["text", "field", "barcode", "qr"])
def test_image_field_rejects_non_photo(prj, t):
    con, _ = prj
    kw = {"field_name": "name"} if t == "field" else {"static_value": "x"}
    el = api.create_element(con, t, 0, 0, 50, 50, **kw)
    with pytest.raises(ValueError, match="только к элементу «фото»"): api.link_field(con, el, "pic")
    assert api.link_field(con, el, "name") is True   # обычные поля — как раньше

def test_photo_rejects_non_image_field(prj):
    con, _ = prj
    ph = api.create_element(con, "photo", 0, 0, 50, 50)
    with pytest.raises(ValueError, match="только к полю типа «изображение»"): api.link_field(con, ph, "name")
    with pytest.raises(ValueError): api.link_field(con, ph, "nope")
    rect = api.create_element(con, "rect", 0, 0, 5, 5)
    with pytest.raises(ValueError): api.link_field(con, rect, "pic")

def test_resolve_photo_path(tmp_path):
    p = {"fields_json": '{"pic": "photos/a.jpg"}', "photo_path": "b.jpg"}
    assert api.resolve_photo_path(p, {"field_name": "pic"}, tmp_path) == tmp_path / "photos/a.jpg"
    assert api.resolve_photo_path(p, "pic", tmp_path) == tmp_path / "photos/a.jpg"
    assert api.resolve_photo_path(p, None, tmp_path) == tmp_path / "b.jpg"
    assert api.resolve_photo_path({"fields": {"pic": ""}, "photo_path": "b.jpg"}, "pic", tmp_path) == tmp_path / "b.jpg"
    assert api.resolve_photo_path({"fields": {}, "photo_path": None}, "pic", tmp_path) is None
    assert api.resolve_photo_path(p, "pic").is_absolute()

def _center(con, pid, base):
    return render_card_db(con, pid, "front", base).convert("RGB").getpixel((50, 50))

def test_render_from_field_and_fallback(prj):
    con, d = prj
    _img(d / "old.png", "blue")
    ph = api.create_element(con, "photo", 0, 0, 100, 100); api.link_field(con, ph, "pic")
    pid = api.create_person(con, {"name": "А"}, photo_path="old.png")
    assert _center(con, pid, d)[2] > 200                       # поле пусто → persons.photo_path (синий)
    rel = api.save_photo(con, (_img(d / "src.png", "red")).read_bytes(), ext="png")
    api.update_person(con, pid, {"pic": rel})
    assert api.get_person(con, pid)["fields"]["pic"] == rel
    assert _center(con, pid, d)[0] > 200                       # из image-поля (красный)
    api.unlink_field(con, ph)
    assert _center(con, pid, d)[2] > 200                       # отвязан → снова photo_path

def test_db_export_copies_field_photos_and_round_trip(prj):
    con, d = prj
    _img(d / "old.png", "blue")
    ph = api.create_element(con, "photo", 0, 0, 100, 100); api.link_field(con, ph, "pic")
    rel = api.save_photo(con, _img(d / "src.png", "red").read_bytes(), ext="png")
    pid = api.create_person(con, {"name": "А", "pic": rel}, photo_path="old.png")
    out = d / "exp" / "out.db"; out.parent.mkdir()
    r = api.export_persons(con, out, photo_dir=d)
    assert r["files_copied"] == 2 and r["warnings"] == []
    n = api.connect(out); p = api.list_persons(n)[0]
    name = p["fields"]["pic"]
    assert name == rel.split("/")[-1] and (d / "exp" / "out_photos" / name).is_file() and p["photo_path"] == "old.png"
    assert [e["field_name"] for e in api.list_elements(n) if e["type"] == "photo"] == ["pic"]
    assert _center(n, p["id"], d / "exp" / "out_photos")[0] > 200
    # round-trip: импорт .db в новый проект
    c2 = api.connect(d / "p2.db")
    rep = api.import_rows(c2, api.open_source(out)[0], photo_dir=d / "exp" / "out_photos", import_fields=True)
    assert rep.added == 1 and rep.errors == []
    q = api.list_persons(c2)[0]
    assert q["fields"]["pic"] == name and {f["name"]: f["data_type"] for f in api.list_fields(c2)}["pic"] == "image"

@pytest.mark.parametrize("payload,code", [(b"", "PHOTO_EMPTY"), (b"junk", "PHOTO_BROKEN")])
def test_import_image_field_bad_file(prj, payload, code):
    con, d = prj
    ph = d / "ph"; _img(ph / "ok.png", "red"); (ph / "bad.png").write_bytes(payload)
    csv = d / "a.csv"; csv.write_text("Имя;Снимок\nА;ok.png\nБ;bad.png\nВ;none.png\n", encoding="utf-8")
    rep = api.import_rows(con, api.open_source(csv)[0], photo_dir=ph)
    assert rep.added == 3 and rep.errors == []
    assert rep.photo_issues == [{"row": 3, "code": code, "file": "bad.png"}]
    assert sorted((w["row"], w["code"]) for w in rep.warnings) == [(3, code), (4, "PHOTO_MISSING")]
    assert [x["fields"].get("pic") for x in api.list_persons(con)] == ["ok.png", None, "none.png"]
