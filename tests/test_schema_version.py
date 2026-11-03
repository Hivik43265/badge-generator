import sqlite3
from badge_backend import api, db

def test_get_schema_version_fresh_and_migrated():
    raw = sqlite3.connect(":memory:")
    assert api.get_schema_version(raw) == 0
    db.migrate(raw)
    assert api.get_schema_version(raw) == len(db.MIGRATIONS) == 4

def test_get_schema_version_connect():
    con = api.connect()
    assert api.get_schema_version(con) == 4
    assert api.get_schema_version is db.get_schema_version
