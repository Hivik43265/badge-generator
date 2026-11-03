import sqlite3, pytest
from badge_backend import api

def test_person_crud(con):
    pid = api.create_person(con, {"last_name": "Иванов"}, "a.jpg", "1;2;1.5;3;4;5")
    p = api.get_person(con, pid)
    assert p["fields"] == {"last_name": "Иванов"} and p["photo_config"] == "1;2;1.5;3;4;5" and p["print_mark"] == 0
    assert api.update_person(con, pid, {"first_name": "Иван"}, print_mark=1)
    p = api.get_person(con, pid); assert p["fields"] == {"last_name": "Иванов", "first_name": "Иван"} and p["print_mark"] == 1
    api.update_person(con, pid, {"x": 1}, merge=False, photo_path=None)
    p = api.get_person(con, pid); assert p["fields"] == {"x": 1} and p["photo_path"] is None
    assert not api.update_person(con, 999, {})
    assert api.delete_person(con, pid) and api.get_person(con, pid) is None and not api.delete_person(con, pid)

def test_update_photo_config(con):
    pid = api.create_person(con, {})
    assert api.update_photo_config(con, pid, "10;-4;2;5;6;-30") == "10;-4;2.0;5;6;-30"
    assert api.update_photo_config(con, pid, api.PhotoConfig(1, 2, 1.5, 0, 0, 0)) == "1;2;1.5;0;0;0"
    with pytest.warns(RuntimeWarning):
        assert api.update_photo_config(con, pid, "0;0;1.0;0.5;0;0") == "0;0;1.0;0;0;0"
    assert api.get_person(con, pid)["photo_config"] == "0;0;1.0;0;0;0"

def test_elements_crud(con):
    e = api.create_element(con, "field", 10.4, 20, 100, 50, field_name="last_name", style={"font_size": 12})
    el = api.list_elements(con)[0]; assert el["x"] == 10 and el["style"] == {"font_size": 12}
    assert api.update_element(con, e, x=30, style={"bold": True}, side="back")
    el = api.list_elements(con, "back")[0]; assert el["x"] == 30 and el["style"] == {"bold": True}
    assert api.list_elements(con, "front") == []
    with pytest.raises(sqlite3.IntegrityError): api.create_element(con, "field", 0, 0, 1, 1)
    with pytest.raises(sqlite3.IntegrityError): api.create_element(con, "circle", 0, 0, 1, 1)
    assert api.delete_element(con, e) and api.list_elements(con) == []

def test_background_and_fields(con):
    api.set_background(con, "front", "#FF0000"); api.set_background(con, "front", "#00FF00", "bg.png")
    assert api.get_background(con, "front") == {"side": "front", "image_path": "bg.png", "color": "#00FF00"}
    assert api.get_background(con, "back") is None
    api.upsert_field(con, "last_name", "Фамилия", 0); api.upsert_field(con, "last_name", "Фам.", 1)
    assert api.list_fields(con) == [{"name": "last_name", "label": "Фам.", "sort_order": 1}]
