import sqlite3, pytest
from badge_backend import api, db
from badge_backend.testing import create_legacy_db

def test_legacy_v1_then_migrate(tmp_path):
    p = create_legacy_db(tmp_path / "old.db", version=1)
    raw = sqlite3.connect(p)
    assert api.get_schema_version(raw) == 1
    assert "printed_at" not in [r[1] for r in raw.execute("PRAGMA table_info(persons)")]
    raw.close()
    con = api.connect(str(p))
    assert api.get_schema_version(con) == db.LATEST
    assert "printed_at" in [r[1] for r in con.execute("PRAGMA table_info(persons)")]

def test_legacy_errors(tmp_path):
    with pytest.raises(ValueError):
        create_legacy_db(tmp_path / "x.db", version=99)
    create_legacy_db(tmp_path / "y.db")
    with pytest.raises(FileExistsError):
        create_legacy_db(tmp_path / "y.db")
