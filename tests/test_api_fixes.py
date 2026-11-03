"""Stage-4 API fixes (расхождения из reports/stage-4-frontend.md) + missing photos."""
from badge_backend.testing import import_with_fields as _imp
import csv, json, re, sqlite3, threading
from pathlib import Path
import pytest
from PIL import Image
from badge_backend import api, demo, db
from badge_backend.services.headers import map_headers

def _csv(p, rows):
    with open(p, "w", newline="", encoding="utf-8") as f: csv.writer(f, delimiter=";").writerows(rows)
    return p

# 1
def test_default_db_path(tmp_path, monkeypatch):
    assert db.DEFAULT_DB_PATH == api.DEFAULT_DB_PATH == "project.db"
    assert db.default_db_path(tmp_path) == tmp_path / "project.db"
    monkeypatch.chdir(tmp_path); assert db.default_db_path() == tmp_path / "project.db"
    api.connect(db.default_db_path()).close(); assert (tmp_path / "project.db").exists()

# 2
def test_mapping_exclude_column(con, tmp_path):
    h = ["Фамилия", "Имя", "Комментарий", "Отдел"]
    assert map_headers(h, {"Комментарий": None, "Отдел": ""}) == ["last_name", "first_name", None, None]
    assert map_headers(h, {"Комментарий": "department", "Отдел": None})[2:] == ["department", None]
    assert map_headers(h, {"last_name": ["Фамилия"], "Комментарий": None}) == ["last_name", "first_name", None, "department"]
    p = _csv(tmp_path / "a.csv", [h, ["Иванов", "Иван", "секрет", "ОК"]])
    r = _imp(api.import_file, con, p, mapping={"Комментарий": None})
    assert r.added == 1 and api.list_persons(con)[0]["fields"] == {"last_name": "Иванов", "first_name": "Иван", "department": "ОК"}
    assert "kommentariy" not in {f["name"] for f in api.list_fields(con)}

# 3
def test_manual_canonical_label_and_labels_param(con, tmp_path):
    p = _csv(tmp_path / "a.csv", [["Фамилия", "Имя", "Комментарий", "Цех"], ["Иванов", "Иван", "ОК", "5"]])
    _imp(api.import_file, con, p, mapping={"Комментарий": "department", "Цех": "workshop"})
    lab = {f["name"]: f["label"] for f in api.list_fields(con)}
    assert lab["department"] == "Отдел" and lab["workshop"] == "Цех"
    assert api.list_persons(con)[0]["fields"]["department"] == "ОК"
    _imp(api.import_file, con, p, mapping={"Комментарий": "department"}, labels={"department": "Подразделение"})
    assert {f["name"]: f["label"] for f in api.list_fields(con)}["department"] == "Подразделение"

# 4
def _photo_csv(tmp_path):
    (tmp_path / "ph").mkdir(exist_ok=True); Image.new("RGB", (30, 40), "red").save(tmp_path / "ph" / "a.jpg")
    return _csv(tmp_path / "p.csv", [["Фамилия", "Имя", "Фото"], ["Иванов", "Иван", "a.jpg"], ["Петров", "Пётр", ""]])

def test_import_photo_missing_default_is_warning(con, tmp_path):
    r = _imp(api.import_file, con, _photo_csv(tmp_path), photo_dir=tmp_path / "ph")
    assert (r.added, r.skipped, r.errors) == (2, 0, [])
    assert [(w["row"], w["code"]) for w in r.warnings] == [(3, "PHOTO_MISSING")]
    p = api.get_person(con, r.ids[1]); assert p["photo_path"] is None and p["photo_config"] == "0;0;1.0;0;0;0"
    img = api.render_card_db(con, r.ids[1], "front"); assert img.size == (1011, 638)

def test_import_require_photo_strict(con, tmp_path):
    r = _imp(api.import_file, con, _photo_csv(tmp_path), photo_dir=tmp_path / "ph", require_photo=True)
    assert (r.added, r.skipped) == (1, 1) and [e["code"] for e in r.errors] == ["PHOTO_MISSING"] and r.warnings == []
    r = _imp(api.import_file, api.connect(), _photo_csv(tmp_path), require_photo=True)   # и без photo_dir
    assert (3, "PHOTO_MISSING") in {(e["row"], e["code"]) for e in r.errors}

def test_import_fallback_photo_missing(con, tmp_path, monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "data_tools", None)
    with pytest.warns(RuntimeWarning):
        r = _imp(api.import_file, con, _photo_csv(tmp_path), photo_dir=tmp_path / "ph")
    assert r.added == 2 and [w["code"] for w in r.warnings] == ["PHOTO_MISSING"]

# 5
def test_import_progress_and_cancel(con, tmp_path):
    p = _csv(tmp_path / "a.csv", [["Фамилия", "Имя"]] + [[f"Ф{i}", "И"] for i in range(20)])
    calls = []; r = _imp(api.import_file, con, p, progress=lambda d, t: calls.append((d, t)))
    assert calls[0] == (0, 20) and calls[-1] == (20, 20) and r.added == 20
    c2 = api.connect(); r = _imp(api.import_file, c2, p, progress=lambda d, t: d < 10)
    assert r.cancelled and r.added == 0 and c2.execute("SELECT COUNT(*) FROM persons").fetchone()[0] == 0

def test_export_progress_and_cancel(demo_db, tmp_path):
    c, ids, d = demo_db
    calls = []
    files = api.export_png(c, None, tmp_path / "o", base_dir=d, allow_missing_photo=True, progress=lambda a, b: calls.append((a, b)))
    assert len(files) == 4 and calls[-1] == (4, 4) and not files.cancelled
    files = api.export_png(c, None, tmp_path / "o2", base_dir=d, allow_missing_photo=True, progress=lambda a, b: a < 2)
    assert len(files) == 2 and files.cancelled
    assert api.export_pdf(c, None, tmp_path / "x.pdf", base_dir=d, allow_missing_photo=True, progress=lambda a, b: a < 1) is None
    assert not (tmp_path / "x.pdf").exists()

# 7
@pytest.mark.parametrize("form", ["json_str", "json_dict", "fields", "row"])
def test_person_formats(form):
    els = [dict(type="field", x=0, y=0, w=1011, h=638, field_name="last_name", style_json='{"font_size":40}')]
    ref = api.render_card({"fields_json": '{"last_name":"Ёжиков"}'}, els)
    if form == "json_str": p = {"fields_json": '{"last_name":"Ёжиков"}'}
    elif form == "json_dict": p = {"fields_json": {"last_name": "Ёжиков"}}
    elif form == "fields": p = {"fields": {"last_name": "Ёжиков"}, "photo_path": None, "photo_config": None}
    else:
        c = api.connect(); pid = api.create_person(c, {"last_name": "Ёжиков"})
        p = c.execute("SELECT * FROM persons WHERE id=?", (pid,)).fetchone(); assert isinstance(p, sqlite3.Row)
    assert api.render_card(p, els).tobytes() == ref.tobytes()

def test_render_preview_with_draft_dict(demo_db):
    c, ids, d = demo_db
    im = api.render_preview(c, {"fields": {"last_name": "Черновик"}, "photo_config": "0;0;1.0;0;0;0"}, "front", 0.5, base_dir=d)
    assert im.size == (506, 319)

# 8
def test_snapshot_export_in_thread_memory_db(demo_db, tmp_path):
    c, ids, d = demo_db                      # c — ':memory:'
    snap = api.snapshot(c, None, ("front", "back"))
    assert len(snap) == 4 and {j["side"] for j in snap} == {"front", "back"}
    assert all(isinstance(j["person"], dict) and isinstance(j["elements"], list) for j in snap)
    res = {}
    def work():
        res["png"] = api.export_png_from_snapshot(snap, tmp_path / "t", base_dir=d, allow_missing_photo=True)
        res["pdf"] = api.export_pdf_from_snapshot(snap, tmp_path / "t.pdf", base_dir=d, allow_missing_photo=True)
    t = threading.Thread(target=work); t.start(); t.join()
    assert len(res["png"]) == 4 and res["pdf"].exists()
    assert len(re.findall(rb"/Type\s*/Page[^s]", res["pdf"].read_bytes())) == 4
    assert api.snapshot(c, [ids[2], 999], "front")[0]["person"]["id"] == ids[2] and len(api.snapshot(c, [ids[2], 999], "front")) == 1

# missing photos
def test_missing_photos_precheck(demo_db):
    c, ids, d = demo_db                      # ids[0] — есть фото, ids[1] — nope.jpg, ids[2] — без фото (не помечен)
    assert api.missing_photos(c, base_dir=d) == [ids[1]]
    assert api.missing_photos(c, ids, base_dir=d) == [ids[1], ids[2]]
    (d / "zero.jpg").write_bytes(b""); api.update_person(c, ids[0], photo_path="zero.jpg")
    assert api.missing_photos(c, base_dir=d) == [ids[0], ids[1]]

def test_export_missing_photo_strict_and_allowed(demo_db, tmp_path):
    c, ids, d = demo_db
    with pytest.raises(api.MissingPhotosError) as ei: api.export_png(c, None, tmp_path / "s", base_dir=d)
    assert ei.value.ids == [ids[1]] and not (tmp_path / "s").exists() or not list((tmp_path / "s").iterdir())
    with pytest.raises(api.MissingPhotosError): api.export_pdf(c, None, tmp_path / "s.pdf", base_dir=d)
    assert not (tmp_path / "s.pdf").exists()
    r = api.export_png(c, None, tmp_path / "a", base_dir=d, allow_missing_photo=True)
    assert len(r) == 4 and r.missing_photo_ids == [ids[1]]
    r = api.export_pdf(c, None, tmp_path / "a.pdf", base_dir=d, allow_missing_photo=True)
    assert r.exists() and r.missing_photo_ids == [ids[1]] and isinstance(r, Path)
    ok = api.export_png(c, [ids[0]], tmp_path / "b", "front", base_dir=d)   # все с фото — исключения нет
    assert len(ok) == 1 and ok.missing_photo_ids == []
