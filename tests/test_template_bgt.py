"""Этап 15 B4: экспорт/импорт шаблона .bgt — замена активного шаблона."""
import io, json, zipfile
from pathlib import Path
from PIL import Image
import pytest
from badge_backend import api, db
from badge_backend.render import render_card_db
from badge_backend.services import templates as T
from badge_backend.services.template_file import export_template, import_template, preview_template_file
from tests.image_assert import assert_same_pixels


def _bg(path, color=(10, 20, 30)):
    Image.new("RGB", (40, 30), color).save(path)


def _project(tmp_path, name="p.db"):
    con = api.connect(tmp_path / name)
    api.upsert_field(con, "fio", "ФИО")
    api.upsert_field(con, "photo", "Фото", data_type="image")
    return con


def test_import_replaces_active_adds_no_template(tmp_path):
    con = _project(tmp_path)
    api.create_element(con, "text", 1, 2, 30, 10, static_value="OLD")
    T.set_template_style(con, {"font_family": "DejaVu Sans", "padding": 4})
    tid = T.get_active_template(con)["id"]
    T.create_template(con, "Другой")
    n_before = len(T.list_templates(con))
    # шаблон для экспорта
    con2 = _project(tmp_path, "src.db")
    api.create_element(con2, "field", 10, 20, 100, 40, field_name="fio")
    api.create_element(con2, "photo", 5, 5, 50, 60, field_name="photo")
    T.set_template_style(con2, {"padding": 12})
    T.rename_template(con2, T.get_active_template(con2)["id"], "Импортный")
    _bg(tmp_path / "front.png", (200, 10, 10))
    api.set_background(con2, "front", color="#ABCDEF", image_path="front.png")
    bgt = export_template(con2, tmp_path / "t.bgt")
    r = import_template(con, bgt)
    assert r["template_id"] == tid and r["active_template_id"] == tid
    assert len(T.list_templates(con)) == n_before
    assert T.get_active_template(con)["id"] == tid
    els = api.list_elements(con)
    assert len(els) == 2 and {e["type"] for e in els} == {"field", "photo"}
    assert all(e.get("static_value") != "OLD" for e in els)
    assert T.get_template_style(con)["padding"] == 12
    assert api.get_background(con, "front")["color"].upper() in ("#ABCDEF", "ABCDEF")
    assert r["name"] == "Импортный"


def test_import_unlinks_missing_fields(tmp_path):
    src = _project(tmp_path, "s.db")
    api.upsert_field(src, "title", "Должность")
    api.create_element(src, "field", 0, 0, 80, 20, field_name="title")
    api.create_element(src, "field", 0, 30, 80, 20, field_name="fio")
    bgt = export_template(src, tmp_path / "u.bgt")
    dst = api.connect(tmp_path / "d.db")
    api.upsert_field(dst, "fio", "ФИО")
    prev = preview_template_file(bgt, dst)
    assert "title" in prev["missing_fields"]
    assert any(o["field_name"] == "title" for o in prev["unlinked_objects"])
    r = import_template(dst, bgt)
    assert "title" in r["unlinked_fields"]
    els = api.list_elements(dst)
    titles = [e for e in els if e["static_value"] is None and e["type"] == "field"]
    unlinked = [e for e in els if e["field_name"] is None]
    linked = [e for e in els if e["field_name"] == "fio"]
    assert unlinked and linked
    assert all(x["type"] == "field" for x in unlinked)
    assert "title" not in {f["name"] for f in api.list_fields(dst)}


def test_zip_slip_and_limits(tmp_path):
    con = _project(tmp_path)
    n_els = len(api.list_elements(con))
    def pack(name, members):
        p = tmp_path / name
        with zipfile.ZipFile(p, "w") as zf:
            for arc, data in members:
                zf.writestr(arc, data)
        return p
    payload = json.dumps({"format": "badge-generator-template", "format_version": 1,
                          "template": {"name": "X", "style": {}}, "elements": [], "backgrounds": []})
    evil = pack("evil.bgt", [("template.json", payload), ("../evil.txt", b"nope")])
    with pytest.raises(ValueError, match="опасный"):
        import_template(con, evil)
    assert not (tmp_path / "evil.txt").exists()
    absn = pack("abs.bgt", [("template.json", payload), ("C:/Windows/a.png", b"xx")])
    with pytest.raises(ValueError, match="опасный"):
        import_template(con, absn)
    many = [("template.json", payload)] + [(f"f{i}.txt", b"a") for i in range(65)]
    with pytest.raises(ValueError, match="много"):
        preview_template_file(pack("many.bgt", many))
    assert len(api.list_elements(con)) == n_els


def test_bad_format(tmp_path):
    con = _project(tmp_path)
    p = tmp_path / "bad.bgt"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("template.json", json.dumps({
            "format": "badge-generator-template", "format_version": 99,
            "template": {"name": "X"}, "elements": []}))
    with pytest.raises(ValueError, match="верси"):
        import_template(con, p)
    p2 = tmp_path / "notzip.bgt"; p2.write_text("nope")
    with pytest.raises(ValueError):
        preview_template_file(p2)
    p3 = tmp_path / "unk.bgt"
    with zipfile.ZipFile(p3, "w") as zf:
        zf.writestr("template.json", json.dumps({
            "format": "badge-generator-template", "format_version": 1,
            "template": {"name": "X"}, "elements": [{"type": "spaceship", "x": 0, "y": 0, "w": 1, "h": 1}]}))
    with pytest.raises(ValueError, match="тип"):
        import_template(con, p3)


def test_name_suffix_when_taken_by_another(tmp_path):
    con = _project(tmp_path)
    T.rename_template(con, T.get_active_template(con)["id"], "Основной")
    T.create_template(con, "Пропуск")
    src = _project(tmp_path, "s.db")
    T.rename_template(src, T.get_active_template(src)["id"], "Пропуск")
    api.create_element(src, "text", 0, 0, 10, 10, static_value="N")
    bgt = export_template(src, tmp_path / "имя шаблона.bgt")
    r = import_template(con, bgt)
    assert r["name"] == "Пропуск (2)" and r["renamed_from"] == "Пропуск"
    assert r["template_id"] == T.get_active_template(con)["id"]
    names = {t["name"] for t in T.list_templates(con)}
    assert "Пропуск" in names and "Пропуск (2)" in names


def test_forbidden_in_template_edit_mode(tmp_path):
    con = _project(tmp_path)
    src = _project(tmp_path, "s.db")
    api.create_element(src, "text", 0, 0, 10, 10, static_value="Z")
    bgt = export_template(src, tmp_path / "e.bgt")
    T.begin_template_edit(con)
    with pytest.raises(api.TemplateEditActiveError):
        import_template(con, bgt)
    T.cancel_template_edit(con)


def test_export_import_identical_card(tmp_path):
    con = _project(tmp_path)
    api.create_element(con, "field", 20, 20, 200, 40, field_name="fio")
    api.create_element(con, "photo", 20, 80, 80, 100, field_name="photo")
    T.set_template_style(con, {"padding": 9})
    _bg(tmp_path / "f.jpg", (30, 80, 120))
    api.set_background(con, "front", color="#112233", image_path="f.jpg")
    pid = api.create_person(con, {"fio": "Иванов", "photo": None})
    before = render_card_db(con, pid, "front", str(tmp_path))
    bgt = export_template(con, tmp_path / "card.bgt")
    # испортить активный шаблон
    for e in api.list_elements(con):
        api.delete_element(con, e["id"])
    api.create_element(con, "text", 0, 0, 50, 20, static_value="мусор")
    r = import_template(con, bgt)
    assert r["unlinked_objects"] == []
    after = render_card_db(con, pid, "front", str(tmp_path))
    assert_same_pixels(before, after)


def test_cyrillic_filename(tmp_path):
    con = _project(tmp_path)
    api.create_element(con, "text", 0, 0, 20, 10, static_value="Привет")
    T.rename_template(con, T.get_active_template(con)["id"], "Шаблон сотрудника")
    p = export_template(con, tmp_path / "шаблон сотрудника")
    assert p.suffix == ".bgt" and p.is_file()
    dst = _project(tmp_path, "d.db")
    r = import_template(dst, p)
    assert r["name"] == "Шаблон сотрудника"
    assert any(e.get("static_value") == "Привет" for e in api.list_elements(dst))


def test_export_overwrite_false_and_true(tmp_path):
    con = _project(tmp_path)
    api.create_element(con, "text", 0, 0, 10, 10, static_value="one")
    dest = tmp_path / "out.bgt"
    p1 = export_template(con, dest)
    assert p1 == dest and dest.is_file()
    first = dest.read_bytes()
    with pytest.raises(FileExistsError):
        export_template(con, dest)
    with pytest.raises(FileExistsError):
        export_template(con, dest, overwrite=False)
    assert dest.read_bytes() == first
    api.create_element(con, "text", 20, 20, 10, 10, static_value="two")
    p2 = export_template(con, dest, overwrite=True)
    assert p2 == dest and dest.read_bytes() != first
    # атомарная запись не оставляет tmp рядом
    assert list(tmp_path.glob("out.bgt*.tmp")) == []
