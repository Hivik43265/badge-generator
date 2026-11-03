"""D19: после create_person/update_person превью и значения не пустые — ключи fields_json = person_fields.name = field_name."""
import pytest
from PIL import ImageChops
from badge_backend import api

FIELDS = [("familiya", "Фамилия"), ("imya", "Имя"), ("last_name", "Фамилия (станд.)"), ("Kafedra", "Кафедра")]

@pytest.fixture
def con():
    c = api.connect()
    for i, (n, l) in enumerate(FIELDS):
        api.upsert_field(c, n, l, i)
        api.create_element(c, "field", 40, 40 + 120 * i, 700, 100, field_name=n, style={"font_size": 40})
    return c

def _diff(con, person, n):
    blank = api.render_preview(con, None, scale=1)
    return ImageChops.difference(api.render_preview(con, person, scale=1).crop((0, 40 + 120 * n, 1011, 140 + 120 * n)),
                                 blank.crop((0, 40 + 120 * n, 1011, 140 + 120 * n))).getbbox()

def test_create_person_custom_and_standard_keys_render(con):
    pid = api.create_person(con, {"familiya": "Ёжиков", "imya": "Пётр", "last_name": "Щукина", "Kafedra": "ИУ7"})
    p = api.get_person(con, pid)
    assert p["fields"] == {"familiya": "Ёжиков", "imya": "Пётр", "last_name": "Щукина", "Kafedra": "ИУ7"}
    assert [f["name"] for f in api.list_fields(con)] == [n for n, _ in FIELDS]       # ключи — name, не label
    for form in (pid, p, {"id": None, "fields_json": p["fields_json"]}, {"fields": p["fields"]}):
        assert all(_diff(con, form, i) is not None for i in range(4)), form

def test_keys_are_exact(con):
    """Ключ — точное имя поля: label или другой регистр не подставляются (так UI и должен передавать name)."""
    pid = api.create_person(con, {"Фамилия": "Ёжиков", "kafedra": "ИУ7"})
    assert _diff(con, pid, 0) is None and _diff(con, pid, 3) is None

def test_update_person_then_render(con):
    pid = api.create_person(con, {})
    assert _diff(con, pid, 0) is None
    api.update_person(con, pid, fields={"familiya": "Ёжиков"})
    assert _diff(con, pid, 0) is not None and api.get_person(con, pid)["fields"] == {"familiya": "Ёжиков"}
