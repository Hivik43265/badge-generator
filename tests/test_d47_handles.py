"""D47: .db-импорт не оставляет открытых дескрипторов (Windows не даёт удалить занятый файл).
На Linux проверяется /proc/self/fd и ResourceWarning как ошибка (Python 3.13: незакрытый sqlite3.Connection)."""
import gc, json, os, sqlite3, warnings
from contextlib import closing
from pathlib import Path
import pytest
from PIL import Image
from badge_backend import api
from badge_backend.services.sources import Sheet
from badge_backend.testing import create_legacy_db, import_with_fields as _imp

pytestmark = [pytest.mark.filterwarnings("error::ResourceWarning"),
              pytest.mark.filterwarnings("error::pytest.PytestUnraisableExceptionWarning")]   # ResourceWarning из __del__

def _open_fds(path):
    d = Path("/proc/self/fd")
    if not d.is_dir(): pytest.skip("нет /proc/self/fd")
    target = os.path.realpath(path); out = []
    for fd in os.listdir(d):
        try:
            if os.path.realpath(os.readlink(d / fd)).startswith(target): out.append(fd)   # и -journal/-wal
        except OSError: pass
    return out

@pytest.mark.parametrize("ver", [1, 4])
def test_db_import_leaves_no_open_handles(tmp_path, ver):
    with warnings.catch_warnings():              # мусор от ДРУГИХ тестов не приписывается этому
        warnings.simplefilter("ignore"); gc.collect()
    p = create_legacy_db(tmp_path / f"v{ver}.db", version=ver)
    with closing(sqlite3.connect(p)) as raw:
        raw.execute("INSERT INTO person_fields(name,label,sort_order) VALUES ('a','A',0)")
        raw.execute("INSERT INTO persons(fields_json,photo_path) VALUES (?, 'f.jpg')", (json.dumps({"a": "x"}),)); raw.commit()
    Image.new("RGB", (5, 5)).save(tmp_path / "f.jpg")
    sh = api.open_source(p); w = sh[0].work_path
    with closing(api.connect()) as con:
        _imp(api.import_rows, con, sh[0], photo_dir=tmp_path)
        api.read_rows(sh[0])
    gc.collect()
    assert _open_fds(w) == [] and _open_fds(p) == []
    sh[0].close(); assert not w.exists()

def test_close_reraises_when_unlink_fails(tmp_path, monkeypatch):
    f = tmp_path / "w.db"; f.write_bytes(b"x")
    s = Sheet(tmp_path / "src.db", "persons", "project", 0, f, 1)
    def boom(self, missing_ok=False): raise PermissionError("busy")
    monkeypatch.setattr(Path, "unlink", boom)
    with pytest.raises(PermissionError): s.close()
    assert s.work_path == f                      # можно повторить close() после освобождения файла
    monkeypatch.undo(); s.close(); assert not f.exists() and s.work_path is None
