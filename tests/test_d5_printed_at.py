"""D5: миграция v2 (persons.printed_at) и mark_printed."""
import json, re, sqlite3, pytest
from badge_backend import api, db

ISO = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")

def _v1(path):
    con = sqlite3.connect(str(path))
    con.executescript(db.SCHEMA + "\nPRAGMA user_version=1;")
    con.execute("INSERT INTO persons(fields_json, photo_path, photo_config, print_mark) VALUES (?,?,?,1)",
                ('{"last_name":"Иванов"}', "a.jpg", "5;-3;1.25;10;20;15"))
    con.execute("INSERT INTO persons(fields_json) VALUES ('{\"last_name\":\"Петров\"}')")
    con.commit(); return con

def test_migrate_old_v1_db(tmp_path):
    p = tmp_path / "old.db"; old = _v1(p)
    before = [tuple(r) for r in old.execute("SELECT * FROM persons ORDER BY id")]; old.close()
    assert "printed_at" not in db._cols(sqlite3.connect(str(p)), "persons")
    con = api.connect(p)
    assert con.execute("PRAGMA user_version").fetchone()[0] == 7 == db.LATEST
    assert "printed_at" in db._cols(con, "persons")
    after = [tuple(r) for r in con.execute("SELECT * FROM persons ORDER BY id")]
    # v7: photo_path копируется в новое поле «Фото», created_at/updated_at (UTC) → локальное время со смещением
    exp = []
    for b in before:
        fj = json.loads(b[1])
        if b[2]: fj["Фото"] = b[2]
        exp.append((b[0], fj, *b[2:5], db._utc_to_local(b[5]), db._utc_to_local(b[6])))
    assert [(a[0], json.loads(a[1]), *a[2:5], a[5], a[6]) for a in after] == exp and all(a[-1] is None for a in after)
    assert all("T" in a[5] and "T" in a[6] for a in after)
    assert [x["printed_at"] for x in api.list_persons(con)] == [None, None]

def test_migrate_repeat_idempotent(tmp_path):
    p = tmp_path / "x.db"; c = api.connect(p); c.close()
    c = api.connect(p); assert db.migrate(c) == db.LATEST and db.migrate(c) == db.LATEST
    # столбец уже есть, а version откатили — шаг всё равно не падает
    c.execute("PRAGMA user_version=1"); assert db.migrate(c) == db.LATEST
    assert sum(1 for col in db._cols(c, "persons") if col == "printed_at") == 1

def test_new_db_has_printed_at():
    c = api.connect(); pid = api.create_person(c, {"last_name": "А"})
    assert api.get_person(c, pid)["printed_at"] is None

def test_mark_printed_sets_time_and_clears_mark():
    c = api.connect(); a = api.create_person(c, {"x": 1}, print_mark=1); b = api.create_person(c, {"x": 2}, print_mark=1)
    assert api.mark_printed(c, [a]) == 1
    pa, pb = api.get_person(c, a), api.get_person(c, b)
    assert pa["print_mark"] == 0 and ISO.match(pa["printed_at"]), pa["printed_at"]
    assert pb["print_mark"] == 1 and pb["printed_at"] is None
    assert api.mark_printed(c, []) == 0

def test_set_print_mark_keeps_printed_at():
    c = api.connect(); a = api.create_person(c, {"x": 1}, print_mark=1)
    api.mark_printed(c, [a]); t = api.get_person(c, a)["printed_at"]
    assert api.set_print_mark(c, [a], True) == 1 and api.get_person(c, a)["print_mark"] == 1
    assert api.set_print_mark(c, [a], False) == 1 and api.get_person(c, a)["print_mark"] == 0
    assert api.get_person(c, a)["printed_at"] == t and api.set_print_mark(c, [], True) == 0

@pytest.mark.parametrize("args", [(False,), (True,), ()])
def test_mark_printed_has_no_value_param(args):
    c = api.connect(); a = api.create_person(c, {"x": 1}, print_mark=1)
    if args:
        with pytest.raises(TypeError): api.mark_printed(c, [a], *args)
        with pytest.raises(TypeError): api.mark_printed(c, [a], value=args[0])
        assert api.get_person(c, a)["print_mark"] == 1 and api.get_person(c, a)["printed_at"] is None
    else:
        assert api.mark_printed(c, [a]) == 1 and api.get_person(c, a)["print_mark"] == 0

def test_mark_printed_no_value_no_warning():
    import warnings
    c = api.connect(); a = api.create_person(c, {"x": 1}, print_mark=1)
    with warnings.catch_warnings():
        warnings.simplefilter("error"); assert api.mark_printed(c, [a]) == 1

def test_mark_printed_rollback(monkeypatch):
    c = api.connect(); a = api.create_person(c, {"x": 1}, print_mark=1)
    c.execute("CREATE TRIGGER boom2 AFTER UPDATE ON persons WHEN NEW.printed_at IS NOT NULL "
              "AND (SELECT COUNT(*) FROM persons WHERE printed_at IS NOT NULL)=2 BEGIN SELECT RAISE(ABORT,'fail'); END")
    b = api.create_person(c, {"x": 2}, print_mark=1)
    with pytest.raises(sqlite3.IntegrityError):
        api.mark_printed(c, [a, b])
    assert all(p["print_mark"] == 1 and p["printed_at"] is None for p in api.list_persons(c))
