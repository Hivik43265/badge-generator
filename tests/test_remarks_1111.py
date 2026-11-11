"""Замечания Ивана 11.11 (пакет из 7): тесты только на новое поведение (QA, BG-Тесты)."""
import json, sqlite3, sys
from pathlib import Path
import pytest
from badge_backend import api, db, app_paths
from badge_backend.render import render_card, render_card_db
from badge_backend.services import photo_edit as PE


# ---------- №1: app_paths / BG_APP_ROOT ----------
def test_app_root_env_and_lazy_dirs(tmp_path, monkeypatch):
    root = tmp_path / "app"
    monkeypatch.setenv("BG_APP_ROOT", str(root))
    assert app_paths.app_root() == root.absolute()
    assert not root.exists()                                   # ничего не создаётся заранее
    for fn, name in ((app_paths.work_dir, "work"), (app_paths.import_dir, "import"),
                     (app_paths.logs_dir, "logs"), (app_paths.projects_dir, "projects")):
        d = fn(); assert d == root / name and d.is_dir()
    assert app_paths.assets_dir() == root / "assets" and not (root / "assets").exists()


def test_app_root_frozen_is_exe_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("BG_APP_ROOT", raising=False)
    exe = tmp_path / "dist" / "BadgeGenerator" / "BadgeGenerator.exe"; exe.parent.mkdir(parents=True); exe.write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert app_paths.app_root() == exe.parent.resolve()


def test_app_root_from_sources_is_repo(monkeypatch):
    monkeypatch.delenv("BG_APP_ROOT", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert app_paths.app_root() == Path(app_paths.__file__).resolve().parent.parent


def test_fallback_root_when_not_writable(tmp_path, monkeypatch):
    monkeypatch.setenv("BG_APP_ROOT", str(tmp_path / "ro"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    real = app_paths._writable_dir
    monkeypatch.setattr(app_paths, "_writable_dir", lambda d: False if "ro" in d.parts else real(d))
    assert app_paths.logs_dir() == tmp_path / "local" / "BadgeGenerator" / "logs"


def test_frozen_db_in_projects_and_legacy_copy(tmp_path, monkeypatch):
    """№1 (доп.): БД exe — <папка программы>/projects/project.db; старая %APPDATA%-БД копируется со спутниками."""
    mei = tmp_path / "_MEI1"; mei.mkdir(); root = tmp_path / "app"
    monkeypatch.setattr(sys, "frozen", True, raising=False); monkeypatch.setattr(sys, "_MEIPASS", str(mei), raising=False)
    monkeypatch.setenv("BG_APP_ROOT", str(root)); monkeypatch.setenv("APPDATA", str(tmp_path / "AppData"))
    old = tmp_path / "AppData" / "BadgeGenerator"; (old / "photos").mkdir(parents=True)
    api.connect(old / "project.db").close(); (old / "photos" / "a.jpg").write_bytes(b"jpg"); (old / "project.csd").write_bytes(b"csd")
    before = (old / "project.db").read_bytes()
    new = db.default_db_path()
    assert new == root / "projects" / "project.db" and new.is_file()
    assert (new.parent / "photos" / "a.jpg").read_bytes() == b"jpg" and (new.parent / "project.csd").is_file()
    assert (old / "project.db").read_bytes() == before                  # копия, оригинал на месте
    new.write_bytes(b"mine"); assert db.default_db_path() == new and new.read_bytes() == b"mine"   # не перезаписывает


def test_bundled_assets_found():
    assert app_paths.find_asset("fonts", "DejaVuSans.ttf") is not None
    assert app_paths.find_asset("smartid", "reference.csd") is not None


# ---------- №2: «Портрет» ----------
def test_portrait_constants():
    assert PE.HEADROOM == pytest.approx(0.05) and PE.HEAD_SHARE == pytest.approx(0.75)


# ---------- №3: bold / italic ----------
def _txt(style):
    st = {"font_size": 14, "font_family": "DejaVu Sans", **style}
    return render_card(None, [dict(type="text", x=20, y=20, w=700, h=150, static_value="Жирный Курсив",
                                   style_json=json.dumps(st))]).tobytes()


def test_bold_italic_render_and_legacy_keys():
    plain, bold, ital, both = _txt({}), _txt({"bold": True}), _txt({"italic": True}), _txt({"bold": True, "italic": True})
    assert len({plain, bold, ital, both}) == 4
    assert _txt({"font_weight": 700}) == bold and _txt({"font_style": "italic"}) == ital
    assert _txt({"bold": False, "italic": False}) == plain


# ---------- №4: без авто-полей, миграция v9 ----------
def test_no_auto_fields_new_project():
    con = api.connect()
    api.create_element(con, "photo", 0, 0, 100, 120)
    api.create_element(con, "image", 200, 0, 100, 100)
    assert api.list_fields(con) == [] and api.list_image_fields(con) == []


def test_list_image_fields_only_image():
    con = api.connect(); api.upsert_field(con, "fio", "ФИО"); api.upsert_field(con, "pic", "Портрет", data_type="image")
    assert [f["name"] for f in api.list_image_fields(con)] == ["pic"]


def _v8_with_auto(path):
    raw = sqlite3.connect(path); v0 = db.LATEST; db.LATEST = 8
    try: db.migrate(raw)
    finally: db.LATEST = v0
    raw.executescript("""
      INSERT INTO person_fields(name,label,sort_order,data_type) VALUES ('pic','Портрет',0,'image'),('Фото','Фото',1,'image'),('Фото 2','Фото 2',2,'image');
      INSERT INTO persons(fields_json,print_mark,created_at,updated_at) VALUES
        ('{"Фото":"a.jpg"}',0,'2026-01-01T09:00:00+03:00','2026-01-01T10:00:00+03:00'),
        ('{"pic":"own.jpg","Фото":"other.jpg"}',0,'2026-01-01T09:00:00+03:00','2026-01-01T10:00:00+03:00'),
        ('{"pic":"same.jpg","Фото 2":"same.jpg"}',0,'2026-01-01T09:00:00+03:00','2026-01-01T10:00:00+03:00');
      INSERT INTO template_elements(type,x,y,w,h,field_name,side,z_order,template_id) VALUES ('photo',0,0,100,120,'Фото','front',0,1);
    """); raw.commit(); raw.close()


def test_v9_merges_auto_photo_fields(tmp_path):
    p = tmp_path / "v8.db"; _v8_with_auto(p)
    con = db.connect(str(p)); assert db.get_schema_version(con) == db.LATEST >= 9
    assert [f["name"] for f in api.list_image_fields(con)] == ["pic"]
    f = {r["id"]: json.loads(r["fields_json"]) for r in con.execute("SELECT id, fields_json FROM persons")}
    assert f[1] == {"pic": "a.jpg"}                                    # перенос в своё поле
    assert f[2] == {"pic": "own.jpg", "Фото": "other.jpg"}             # конфликт — данные не теряются
    assert f[3] == {"pic": "same.jpg"}                                 # одинаковые — дубль убран
    assert [e["field_name"] for e in api.list_elements(con)] == ["pic"]   # перепривязка объекта
    assert {r[0] for r in con.execute("SELECT updated_at FROM persons")} == {"2026-01-01T10:00:00+03:00"}


def _v8_raw(path, sql):
    raw = sqlite3.connect(path); v0 = db.LATEST; db.LATEST = 8
    try: db.migrate(raw)
    finally: db.LATEST = v0
    raw.executescript(sql); raw.commit(); raw.close()
    return db.connect(str(path))


def test_v9_logo_not_merged(tmp_path):
    """№4 (доп.): logo не сливается в своё поле; пустое и ни к чему не привязанное logo удаляется, иначе остаётся."""
    con = _v8_raw(tmp_path / "a.db", """
      INSERT INTO person_fields(name,label,sort_order,data_type) VALUES ('pic','Портрет',0,'image'),('logo','Логотип',1,'image');
      INSERT INTO persons(fields_json,print_mark) VALUES ('{"logo":""}',0);""")
    assert [f["name"] for f in api.list_image_fields(con)] == ["pic"]
    con = _v8_raw(tmp_path / "b.db", """
      INSERT INTO person_fields(name,label,sort_order,data_type) VALUES ('pic','Портрет',0,'image'),('logo','Логотип',1,'image');
      INSERT INTO persons(fields_json,print_mark) VALUES ('{"logo":"l.png"}',0);""")
    assert [f["name"] for f in api.list_image_fields(con)] == ["pic", "logo"]
    assert json.loads(con.execute("SELECT fields_json FROM persons").fetchone()[0]) == {"logo": "l.png"}
    con = _v8_raw(tmp_path / "c.db", """
      INSERT INTO person_fields(name,label,sort_order,data_type) VALUES ('pic','Портрет',0,'image'),('logo','Логотип',1,'image');
      INSERT INTO template_elements(type,x,y,w,h,field_name,side,z_order,template_id) VALUES ('photo',0,0,100,100,'logo','front',0,1);""")
    assert [e["field_name"] for e in api.list_elements(con)] == ["logo"] and len(api.list_image_fields(con)) == 2
    snap = json.dumps({"elements": [{"type": "photo", "field_name": "logo"}]})
    con = _v8_raw(tmp_path / "d.db", f"""
      INSERT INTO person_fields(name,label,sort_order,data_type) VALUES ('pic','Портрет',0,'image'),('logo','Логотип',1,'image');
      INSERT OR REPLACE INTO project_settings(key,value) VALUES ('template_edit_snapshot','{snap}');""")
    assert "logo" in [f["name"] for f in api.list_image_fields(con)]   # привязка только в снимке правки — не удаляется


def test_v9_logo_is_not_target_for_auto_photo(tmp_path):
    con = _v8_raw(tmp_path / "a.db", """
      INSERT INTO person_fields(name,label,sort_order,data_type) VALUES ('logo','Логотип',0,'image'),('Фото','Фото',1,'image');
      INSERT INTO persons(fields_json,print_mark) VALUES ('{"logo":"l.png","Фото":"a.jpg"}',0);""")
    assert sorted(f["name"] for f in api.list_image_fields(con)) == ["logo", "Фото"]
    assert json.loads(con.execute("SELECT fields_json FROM persons").fetchone()[0]) == {"logo": "l.png", "Фото": "a.jpg"}


def test_v9_without_own_field_keeps_auto(tmp_path):
    p = tmp_path / "v8.db"; raw = sqlite3.connect(p); v0 = db.LATEST; db.LATEST = 8
    try: db.migrate(raw)
    finally: db.LATEST = v0
    raw.execute("INSERT INTO person_fields(name,label,sort_order,data_type) VALUES ('Фото','Фото',0,'image')"); raw.commit(); raw.close()
    con = db.connect(str(p)); assert [f["name"] for f in api.list_image_fields(con)] == ["Фото"]


# ---------- №5: render_card_db(person=None, field_names=...) ----------
def test_render_card_db_field_names():
    con = api.connect(); api.upsert_field(con, "fio", "ФИО", default_value="Иванов")
    api.create_element(con, "field", 20, 20, 600, 120, field_name="fio")
    names, empty = render_card_db(con, None, field_names=True), render_card_db(con, None, field_names=False)
    assert names.tobytes() != empty.tobytes()
    assert render_card_db(con, None).tobytes() == empty.tobytes()          # по умолчанию — прежний пустой шаблон
    ref = api.connect(); api.create_element(ref, "text", 20, 20, 600, 120, static_value="ФИО")
    assert names.tobytes() == render_card_db(ref, None).tobytes()      # название поля тем же стилем, без красных #поле


def test_render_card_db_photo_placeholder_label():
    con = api.connect(); api.upsert_field(con, "pic", "Портрет", data_type="image")
    api.create_element(con, "photo", 20, 20, 200, 250, field_name="pic")
    assert render_card_db(con, None, field_names=True).tobytes() != render_card_db(con, None).tobytes()


@pytest.mark.parametrize("fn", [True, False])
def test_preview_worker_same_as_render_card_db(tmp_path, fn):
    from ui.backend_api import BackendAPI, render_card_mem
    a = BackendAPI(str(tmp_path / "p.db"), base_dir=str(tmp_path))
    a.upsert_field("fio", "ФИО", 0); a.upsert_field("pic", "Портрет", 1, data_type="image")
    api.create_element(a.con, "field", 20, 20, 600, 120, field_name="fio")
    api.create_element(a.con, "photo", 20, 200, 200, 250, field_name="pic", side="back")
    for side in ("front", "back"):
        got = render_card_mem(**a.gather_render_args(None, side, field_names=fn))
        assert got.tobytes() == render_card_db(a.con, None, side, str(tmp_path), field_names=fn).tobytes()


# ---------- №7: api.set_z_order ----------
def test_set_z_order_ops():
    con = api.connect()
    a, b, c = (api.create_element(con, "rect", i * 10, 0, 50, 50, z_order=i * 5) for i in range(3))
    back = api.create_element(con, "rect", 0, 0, 50, 50, side="back", z_order=7)
    z = lambda: {e["id"]: e["z_order"] for e in api.list_elements(con)}
    assert api.set_z_order(con, a, "front") == 2 and (z()[b], z()[c], z()[a]) == (0, 1, 2)
    assert api.set_z_order(con, a, "back") == 0 and (z()[a], z()[b], z()[c]) == (0, 1, 2)
    assert api.set_z_order(con, a, "up") == 1 and (z()[b], z()[a]) == (0, 1)
    assert api.set_z_order(con, a, "down") == 0
    assert api.set_z_order(con, b, 99) == 2 and api.set_z_order(con, b, -5) == 0
    assert z()[back] == 7                                              # другая сторона не тронута
    assert api.set_z_order(con, 10 ** 6, "front") is None
    with pytest.raises(ValueError): api.set_z_order(con, a, "top")
    with pytest.raises(ValueError): api.set_z_order(con, a, True)
