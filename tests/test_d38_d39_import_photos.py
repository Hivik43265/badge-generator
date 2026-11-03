"""D38: встроенные картинки xlsx → image-поле (или photo_path); D39: фото из папки копируются в photos/."""
import shutil
import pytest
from PIL import Image
from badge_backend import api

def _png(p, color="red", size=(20, 30)):
    p.parent.mkdir(parents=True, exist_ok=True); Image.new("RGB", size, color).save(p); return p

def _xlsx(tmp_path, head="Фото"):
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as XLImage
    g = _png(tmp_path / "g.png", (0, 128, 0))
    wb = Workbook(); ws = wb.active
    ws.append(["Фамилия", head]); ws.append(["Ёжиков", None]); ws.append(["Щукина", None])
    ws.add_image(XLImage(str(g)), "B2"); wb.save(tmp_path / "img.xlsx")
    return api.open_source(tmp_path / "img.xlsx")[0]

def _prj(tmp_path, *image_fields):
    (tmp_path / "prj").mkdir(); con = api.connect(tmp_path / "prj" / "p.db")
    api.upsert_field(con, "last_name", "Фамилия")
    for f in image_fields: api.upsert_field(con, f, f.capitalize(), data_type="image")
    return con

def _opens(con, person, el=None):
    p = api.resolve_photo_path(person, el, api.project_base_dir(con))
    with Image.open(p) as im: im.load(); return im.size

@pytest.mark.parametrize("img_fields,target", [((), "photo_path"), (("pic",), "pic"), (("a", "b"), "a")])
def test_xlsx_embedded_to_target(tmp_path, img_fields, target):
    con = _prj(tmp_path, *img_fields); out = tmp_path / "x"; out.mkdir()
    rep = api.import_rows(con, _xlsx(tmp_path), photo_dir=out)
    assert rep.added == 2
    p0, p1 = api.list_persons(con)
    v = p0["photo_path"] if target == "photo_path" else p0["fields"][target]
    assert v.startswith("photos/") and _opens(con, p0, target if target != "photo_path" else None) == (20, 30)
    if target != "photo_path": assert p0["photo_path"] is None
    assert p1["photo_path"] is None and not any(p1["fields"].get(k) for k in img_fields)
    assert list(out.iterdir()) == []   # извлечённые временные файлы не остаются: фото — в photos/ проекта

def test_xlsx_embedded_follows_mapping(tmp_path):
    con = _prj(tmp_path, "a", "b"); out = tmp_path / "x"; out.mkdir()
    api.import_rows(con, _xlsx(tmp_path, "Снимок"), {"Снимок": "b"}, photo_dir=out)
    p0 = api.list_persons(con)[0]
    assert p0["fields"]["b"].startswith("photos/") and "a" not in p0["fields"]

@pytest.mark.parametrize("img", [False, True])
def test_photo_dir_copied_survives_source_delete(tmp_path, img):
    con = _prj(tmp_path, *(("pic",) if img else ()))
    src = tmp_path / "src"; _png(src / "a.jpg"); _png(src / "b.png", "blue", (7, 9))
    csv = tmp_path / "a.csv"; csv.write_text("Фамилия;Фото\nА;a.jpg\nБ;b.png\nВ;a.jpg\nГ;nope.jpg\n", encoding="utf-8")
    rep = api.import_rows(con, api.open_source(csv)[0], photo_dir=src)
    assert rep.added == 4 and [w["code"] for w in rep.warnings] == ["PHOTO_MISSING"]
    shutil.rmtree(src)
    ps = api.list_persons(con); el = "pic" if img else None
    vals = [(p["fields"].get("pic") if img else p["photo_path"]) for p in ps]
    assert all(v.startswith("photos/") for v in vals[:3]) and vals[0] == vals[2] and vals[3] == "nope.jpg"
    assert [_opens(con, p, el) for p in ps[:3]] == [(20, 30), (7, 9), (20, 30)]
    assert len(list((tmp_path / "prj" / "photos").iterdir())) == 2

@pytest.mark.parametrize("payload,code", [(b"", "PHOTO_EMPTY"), (b"junk", "PHOTO_BROKEN")])
def test_bad_photo_not_copied(tmp_path, payload, code):
    con = _prj(tmp_path); src = tmp_path / "src"; src.mkdir(); (src / "bad.jpg").write_bytes(payload)
    csv = tmp_path / "a.csv"; csv.write_text("Фамилия;Фото\nА;bad.jpg\n", encoding="utf-8")
    rep = api.import_rows(con, api.open_source(csv)[0], photo_dir=src)
    assert rep.added == 1 and rep.photo_issues == [{"row": 2, "code": code, "file": "bad.jpg"}]
    assert api.list_persons(con)[0]["photo_path"] is None and not (tmp_path / "prj" / "photos").exists()

def test_cancel_removes_copies(tmp_path):
    con = _prj(tmp_path); src = tmp_path / "src"; _png(src / "a.jpg")
    csv = tmp_path / "a.csv"; csv.write_text("Фамилия;Фото\nА;a.jpg\nБ;a.jpg\n", encoding="utf-8")
    rep = api.import_rows(con, api.open_source(csv)[0], photo_dir=src, progress=lambda d, t: d < 2)
    assert rep.cancelled and api.list_persons(con) == []
    assert not list((tmp_path / "prj" / "photos").glob("*")) if (tmp_path / "prj" / "photos").exists() else True

def test_in_memory_db_keeps_paths(tmp_path):
    con = api.connect(); api.upsert_field(con, "last_name", "Фамилия"); src = tmp_path / "src"; _png(src / "a.jpg")
    csv = tmp_path / "a.csv"; csv.write_text("Фамилия;Фото\nА;a.jpg\n", encoding="utf-8")
    api.import_rows(con, api.open_source(csv)[0], photo_dir=src)
    assert api.list_persons(con)[0]["photo_path"] == "a.jpg"
