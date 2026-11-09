"""D48: старые рабочие копии .db-импорта удаляются при старте (первый db.connect в процессе)."""
import os, tempfile, time
from pathlib import Path
import pytest
from badge_backend import db
from badge_backend.services import sources

@pytest.fixture
def tmpdir_env(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    d = tmp_path / sources._WORK_DIR_NAME; d.mkdir()
    return tmp_path, d

def _old(p, age=7 * 3600):
    p.write_bytes(b"x"); t = time.time() - age; os.utime(p, (t, t)); return p

def test_removes_only_stale_prefixed_in_own_dir(tmpdir_env):
    root, d = tmpdir_env
    stale = _old(d / "bg_import_abc.db"); journal = _old(d / "bg_import_abc.db-journal")
    fresh = (d / "bg_import_new.db"); fresh.write_bytes(b"x")
    other = _old(d / "user_file.db"); (root / "sub").mkdir(); outside = _old(root / "sub" / "bg_import_out.db")
    removed = sources._cleanup_stale_work_copies()
    assert sorted(removed) == ["bg_import_abc.db", "bg_import_abc.db-journal"]
    assert not stale.exists() and not journal.exists()
    assert fresh.exists() and other.exists() and outside.exists()

def test_unlink_error_does_not_raise(tmpdir_env, monkeypatch, caplog):
    _, d = tmpdir_env; f = _old(d / "bg_import_x.db")
    def boom(self, missing_ok=False): raise PermissionError("locked")
    monkeypatch.setattr(Path, "unlink", boom)
    assert sources._cleanup_stale_work_copies() == [] and f.exists()
    assert "bg_import_x.db" in caplog.text

def test_iterdir_error_does_not_raise(tmpdir_env, monkeypatch):
    def boom(self): raise OSError("io")
    monkeypatch.setattr(Path, "iterdir", boom)
    assert sources._cleanup_stale_work_copies() == []

def test_work_copy_in_own_dir_and_connect_hook(tmpdir_env, monkeypatch):
    root, d = tmpdir_env
    from badge_backend.testing import create_legacy_db
    sh = sources.open_source(create_legacy_db(root / "v1.db", version=1))
    w = sh[0].work_path
    assert w.parent == d and w.name.startswith("bg_import_"); sh[0].close()
    stale = _old(d / "bg_import_left.db")
    monkeypatch.setattr(db, "_cleaned", False)
    db.connect().close()
    assert not stale.exists() and db._cleaned
    stale2 = _old(d / "bg_import_left2.db"); db.connect().close()
    assert stale2.exists()              # только первый connect в процессе

def test_legacy_root_copies(tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    old = _old(tmp_path / "bg_import_old.db"); j = _old(tmp_path / "bg_import_old.db-journal")
    w = _old(tmp_path / "bg_import_old.db-wal"); shm = _old(tmp_path / "bg_import_old.db-shm")
    fresh = tmp_path / "bg_import_x.db"; fresh.write_bytes(b"x")
    keep = [_old(tmp_path / "bg_import_x.txt"), _old(tmp_path / "other_x.db"), _old(tmp_path / "bg_import_x.db-foo"),
            _old(tmp_path / "bg_import_.db")]
    (tmp_path / "sub").mkdir(); keep.append(_old(tmp_path / "sub" / "bg_import_y.db"))
    removed = sources._cleanup_stale_work_copies()
    assert sorted(removed) == sorted(p.name for p in (old, j, w, shm))
    assert fresh.exists() and all(p.exists() for p in keep)
