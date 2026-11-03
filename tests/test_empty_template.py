from badge_backend import api
from badge_backend.render import render_card_db

def test_new_project_has_empty_template(tmp_path):
    con = api.connect(str(tmp_path / "p.db"))
    assert api.list_elements(con) == []

def test_render_empty_template_with_and_without_person():
    con = api.connect()
    pid = api.create_person(con, {"last_name": "Иванов"})
    for side in ("front", "back"):
        for p in (None, pid):
            img = render_card_db(con, p, side=side)
            assert img.size == (1011, 638)
            assert img.getcolors(1) is not None  # однотонный фон

def test_element_crud_and_render():
    con = api.connect()
    pid = api.create_person(con, {"last_name": "Иванов"})
    blank = render_card_db(con, pid).tobytes()
    eid = api.create_element(con, "rect", 10, 10, 200, 100, style={"fill": "#FF0000"})
    fid = api.create_element(con, "field", 10, 150, 500, 60, field_name="last_name")
    assert [e["id"] for e in api.list_elements(con, "front")] == [eid, fid]
    img1 = render_card_db(con, pid)
    assert img1.tobytes() != blank
    assert api.update_element(con, eid, x=300, style={"fill": "#0000FF"})
    e = [e for e in api.list_elements(con) if e["id"] == eid][0]
    assert e["x"] == 300
    assert render_card_db(con, pid).tobytes() != img1.tobytes()
    assert api.delete_element(con, eid) and api.delete_element(con, fid)
    assert api.list_elements(con) == []
    assert render_card_db(con, pid).tobytes() == blank
    assert not api.delete_element(con, eid)
