import sqlite3, warnings, pytest
from badge_backend import CARD_W_PX, CARD_H_PX
from badge_backend.db import connect
from badge_backend.db import LATEST, migrate
from badge_backend.photo_config import PhotoConfig, DEFAULT, normalize

def test_card_px(): assert (CARD_W_PX, CARD_H_PX) == (1011, 638)

def test_migration_from_scratch(tmp_path):
    con = connect(tmp_path / "b.db")
    assert con.execute("PRAGMA user_version").fetchone()[0] == LATEST == 4
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"persons", "template_elements", "person_fields", "template_backgrounds"} <= names
    assert migrate(con) == LATEST  # идемпотентно
    con.close(); assert connect(tmp_path / "b.db").execute("PRAGMA user_version").fetchone()[0] == LATEST

def test_defaults():
    con = connect(); con.execute("INSERT INTO persons(fields_json) VALUES ('{\"fio\":\"Иванов\"}')")
    assert tuple(con.execute("SELECT photo_config, print_mark FROM persons").fetchone()) == (DEFAULT, 0)
    assert DEFAULT == "0;0;1.0;0;0;0"

@pytest.mark.parametrize("sql", [
    "INSERT INTO template_elements(type,x,y,w,h) VALUES ('field',0,0,1,1)",
    "INSERT INTO template_elements(type,x,y,w,h,side) VALUES ('text',0,0,1,1,'top')",
    "INSERT INTO template_elements(type,x,y,w,h) VALUES ('circle',0,0,1,1)",
    "INSERT INTO template_elements(type,x,y,w,h) VALUES ('rect',0,0,0,1)",
    "INSERT INTO template_elements(type,x,y,w,h,style_json) VALUES ('rect',0,0,1,1,'{bad')",
    "INSERT INTO persons(print_mark) VALUES (2)",
    "INSERT INTO persons(fields_json) VALUES ('not json')",
])
def test_checks(sql):
    with pytest.raises(sqlite3.IntegrityError): connect().execute(sql)

@pytest.mark.parametrize("t", ["qr", "barcode", "photo", "image", "text", "rect"])
def test_types_ok(t): connect().execute("INSERT INTO template_elements(type,x,y,w,h) VALUES (?,0,0,1,1)", (t,))

@pytest.mark.parametrize("s,exp", [
    ("0;0;1.0;0;0;0", PhotoConfig()),
    ("10;-5;1.25;120;40;15.5", PhotoConfig(10, -5, 1.25, 120, 40, 15.5)),
    ("3;4;2,5;0;0;-90", PhotoConfig(3, 4, 2.5, 0, 0, -90.0)),
])
def test_roundtrip(s, exp):
    c = PhotoConfig.parse(s); assert c == exp
    assert PhotoConfig.parse(c.dump()) == c and normalize(c.dump()) == c.dump()
    assert PhotoConfig().dump() == DEFAULT

@pytest.mark.parametrize("bad", ["1;2;3", "0;0;0;0;0;0", "0;0;-1;0;0;0", "0;0;1.0;0.5;0;0",
                                 "0;0;1.0;0;1.5;0", "0;0;1.0;-3;0;0", "a;0;1;0;0;0", "0;0;nan;0;0;0", "1.5;0;1;0;0;0"])
def test_bad_gives_default_and_warning(bad, caplog):
    with pytest.warns(RuntimeWarning):
        assert PhotoConfig.parse(bad) == PhotoConfig()
    assert "невалиден" in caplog.text

def test_empty_is_default_silently():
    with warnings.catch_warnings():
        warnings.simplefilter("error"); assert PhotoConfig.parse(None) == PhotoConfig.parse("") == PhotoConfig()
