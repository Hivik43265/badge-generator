"""Этап 15: режим правки шаблона (снимок в project_settings): отмена на любой глубине, восстановление после падения, запреты."""
import json
import pytest
from badge_backend import api, db
from badge_backend.services import templates as T


def _state(con):
    return (json.dumps([dict(r) for r in con.execute("SELECT * FROM template_elements ORDER BY id")], default=str),
            json.dumps([dict(r) for r in con.execute("SELECT * FROM template_backgrounds2")]),
            json.dumps([dict(r) for r in con.execute("SELECT id,name,style_json FROM templates")]),
            json.dumps([dict(r) for r in con.execute("SELECT name FROM person_fields")]))


@pytest.mark.parametrize("depth", [0, 1, 5, 20])
def test_template_edit_cancel_restores(depth):
    con = api.connect(); api.upsert_field(con, "fio", "ФИО")
    e0 = api.create_element(con, "field", 0, 0, 10, 10, field_name="fio")
    s0 = _state(con); T.begin_template_edit(con)
    for i in range(depth):
        api.create_element(con, "text", i, i, 10, 10, static_value=str(i))
        api.upsert_field(con, f"new{i}", f"N{i}"); api.link_field(con, None, f"new{i}")
        api.set_background(con, "front", color="#00000%d" % (i % 10))
        T.set_template_style(con, {"padding": i})
    if depth: api.unlink_field(con, e0); T.rename_template(con, T.get_active_template(con)["id"], "X")
    r = T.cancel_template_edit(con)
    assert _state(con) == s0 and T.get_template_edit_state(con) is None
    assert len(r["removed_fields"]) == depth


def test_template_edit_guards_and_commit():
    con = api.connect(); a = T.get_active_template(con)["id"]; b = T.create_template(con, "B")
    T.begin_template_edit(con)
    with pytest.raises(ValueError): T.begin_template_edit(con)
    with pytest.raises(ValueError): T.set_active_template(con, b)
    with pytest.raises(ValueError): T.delete_template(con, a)
    api.create_element(con, "text", 0, 0, 10, 10, static_value="x")
    assert T.commit_template_edit(con)["id"] == a and T.get_template_edit_state(con) is None
    assert len(api.list_elements(con)) == 1


@pytest.mark.parametrize("keep", [False, True])
def test_template_edit_crash_recovery(tmp_path, keep):
    p = str(tmp_path / "c.db"); con = db.connect(p)
    s0 = _state(con); T.begin_template_edit(con)
    api.create_element(con, "text", 0, 0, 10, 10, static_value="x"); con.close()   # «падение»
    con = db.connect(p); st = T.get_template_edit_state(con)
    assert st and st["elements"] == 0
    if keep: T.commit_template_edit(con); assert len(api.list_elements(con)) == 1
    else: T.cancel_template_edit(con); assert _state(con) == s0
    assert T.get_template_edit_state(con) is None
