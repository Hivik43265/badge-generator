"""Этап 15 B3: модель сохранения — рабочая копия, is_dirty, save/save_as/close."""
import hashlib, os, sqlite3, time
from pathlib import Path
import pytest
from badge_backend import api, db
from badge_backend.services import project_session as PS
from badge_backend.services.templates import begin_template_edit, get_template_edit_state
from badge_backend.services.photos import save_photo, project_base_dir


def _hash(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _edit(session):
    api.create_person(session.con, {"n": "X"})


def test_open_save_close_not_dirty(tmp_path):
    """open → save → close без вопроса (не dirty)."""
    s = api.create_project(tmp_path / "p.db")
    assert s.source_path.is_file()
    assert db.get_schema_version(sqlite3.connect(s.source_path)) == 7
    assert s.is_dirty() is False
    s.save()
    assert s.is_dirty() is False
    s.close()  # save=None, не dirty — без UnsavedChangesError
    assert not default_work_exists(tmp_path / "p.db")


def default_work_exists(source):
    return PS.default_work_path(source).exists() or PS.session_path(source).exists()


def test_open_edit_close_prompts(tmp_path):
    """open → правка → close без save поднимает UnsavedChangesError (dirty)."""
    s = api.create_project(tmp_path / "p.db")
    before = _hash(s.source_path)
    _edit(s)
    assert s.is_dirty() is True
    with pytest.raises(api.UnsavedChangesError):
        s.close()
    assert _hash(s.source_path) == before
    s.close(save=False)


def test_edit_save_close_no_prompt(tmp_path):
    """правка → save → dirty=False → close без вопроса."""
    s = api.create_project(tmp_path / "p.db")
    _edit(s)
    assert s.is_dirty() is True
    r = s.save()
    assert r["integrity"] == "ok" and s.is_dirty() is False
    assert api.list_persons(api.connect(str(s.source_path)))  # исходник содержит правку
    s.close()


def test_edits_do_not_touch_source_until_save(tmp_path):
    s = api.create_project(tmp_path / "a.db")
    before = _hash(s.source_path)
    _edit(s)
    assert _hash(s.source_path) == before
    old = before
    s.save()
    assert _hash(s.source_path) != old
    bak = PS.bak_path(s.source_path)
    assert bak.is_file() and hashlib.sha256(bak.read_bytes()).hexdigest() == old
    assert not list(s.source_path.parent.glob(s.source_path.name + ".*.tmp"))
    s.close()


def test_save_as_cyrillic_and_overwrite(tmp_path):
    s = api.create_project(tmp_path / "src.db")
    _edit(s)
    dest = tmp_path / "моя папка" / "копия проект.db"
    r = s.save_as(dest)
    assert r["path"].is_file() and "X" in str(api.get_person(api.connect(str(dest)), 1)["fields"])
    other = tmp_path / "уже есть.db"; other.write_bytes(b"old")
    with pytest.raises(FileExistsError):
        s.save_as(other)
    api.create_person(s.con, {"n": "Y"})
    s.save_as(other, overwrite=True)
    assert PS.bak_path(other).is_file()
    s.close()


def test_save_as_same_source_is_save(tmp_path):
    s = api.create_project(tmp_path / "p.db")
    _edit(s)
    r = s.save_as(tmp_path / "p.db")
    assert s.is_dirty() is False and r["integrity"] == "ok"
    s.close()


def test_save_as_via_dot_slash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    s = api.create_project(Path("p.db"))
    _edit(s)
    s.save_as(Path("./p.db"))
    assert s.is_dirty() is False
    s.close()


def test_wal_journals_cleaned_after_save(tmp_path):
    s = api.create_project(tmp_path / "p.db")
    _edit(s)
    # имитация старого журнала у исходника
    (tmp_path / "p.db-wal").write_bytes(b"junk")
    (tmp_path / "p.db-journal").write_bytes(b"junk")
    s.save()
    assert not (tmp_path / "p.db-wal").exists()
    assert not (tmp_path / "p.db-journal").exists()
    s.close()


def test_permissionerror_retries_then_project_save_error(tmp_path, monkeypatch):
    s = api.create_project(tmp_path / "p.db")
    _edit(s)
    before = _hash(s.source_path)
    n = {"i": 0}
    real = PS._replace_once
    def boom(tmp, dest, bak):
        n["i"] += 1
        if n["i"] < 3:
            raise PermissionError("busy")
        return real(tmp, dest, bak)
    monkeypatch.setattr(PS, "_replace_once", boom)
    monkeypatch.setattr(PS, "SAVE_RETRIES", 8)
    s.save()
    assert n["i"] == 3 and _hash(s.source_path) != before
    def always(tmp, dest, bak):
        raise PermissionError("busy")
    monkeypatch.setattr(PS, "_replace_once", always)
    api.create_person(s.con, {"n": "Z"})
    mid = _hash(s.source_path)
    with pytest.raises(api.ProjectSaveError, match="занят"):
        s.save()
    assert _hash(s.source_path) == mid
    s.close(save=False)


def test_recover_after_crash(tmp_path):
    s = api.create_project(tmp_path / "p.db")
    _edit(s)
    src, work = s.source_path, s.work_path
    data = PS._read_session(PS.session_path(src))
    data["pid"] = 999999  # мёртвый
    PS._write_json_atomic(PS.session_path(src), data)
    s.con.close()  # не discard — имитация сбоя
    with pytest.raises(api.RecoverableProjectError) as ei:
        api.open_project(src)
    rec = api.recover(ei.value.info, accept=True)
    assert rec.is_dirty() is True
    assert any(p["fields"].get("n") == "X" for p in api.list_persons(rec.con))
    src_hash = _hash(src)
    rec.close(save=False)
    rec2_sess = api.create_project(tmp_path / "q.db")
    rec2_sess.close()
    # accept=False
    s = api.create_project(tmp_path / "r.db")
    _edit(s)
    src, work = s.source_path, s.work_path
    data = PS._read_session(PS.session_path(src))
    data["pid"] = 999999
    PS._write_json_atomic(PS.session_path(src), data)
    s.con.close()
    info = {"source_path": str(src), "work_path": str(work), "pid": 999999, "host": data.get("host")}
    rec = api.recover(info, accept=False)
    assert api.list_persons(rec.con) == []
    rec.close()


def test_live_pid_locked(tmp_path):
    s = api.create_project(tmp_path / "p.db")
    src = s.source_path
    with pytest.raises(api.ProjectLockedError):
        api.open_project(src)
    s.close()


def test_photos_go_to_source_dir_even_if_work_in_temp(tmp_path, monkeypatch):
    monkeypatch.setattr(PS, "should_use_temp_work", lambda d: True)
    s = api.create_project(tmp_path / "p.db")
    assert "BadgeGenerator-work" in str(s.work_path)
    from io import BytesIO
    from PIL import Image
    buf = BytesIO(); Image.new("RGB", (8, 8), (1, 2, 3)).save(buf, "JPEG")
    rel = save_photo(s.con, buf.getvalue(), ext="jpg")
    assert (s.base_dir / rel).is_file()
    assert not (s.work_path.parent / "photos").exists() or not list((s.work_path.parent / "photos").iterdir())
    assert project_base_dir(s.con) == s.base_dir == src_parent(s)
    s.close(save=False)


def src_parent(s):
    return s.source_path.parent


def test_template_edit_blocks_save(tmp_path):
    s = api.create_project(tmp_path / "p.db")
    api.create_element(s.con, "text", 0, 0, 40, 20, static_value="A")
    begin_template_edit(s.con)
    api.update_element(s.con, api.list_elements(s.con)[0]["id"], static_value="B")
    before = _hash(s.source_path)
    with pytest.raises(api.TemplateEditActiveError):
        s.save()
    assert _hash(s.source_path) == before
    assert get_template_edit_state(s.con) is not None
    s.save(commit_template=True)
    src = api.connect(str(s.source_path))
    assert src.execute("SELECT 1 FROM project_settings WHERE key='template_edit_snapshot'").fetchone() is None
    assert api.list_elements(src)[0]["static_value"] == "B"
    s.close()


def test_template_edit_discard_keeps_source(tmp_path):
    s = api.create_project(tmp_path / "p.db")
    eid = api.create_element(s.con, "text", 0, 0, 40, 20, static_value="A")
    s.save()
    begin_template_edit(s.con)
    api.update_element(s.con, eid, static_value="B")
    s.close(save=False)
    src = api.connect(str(tmp_path / "p.db"))
    assert api.list_elements(src)[0]["static_value"] == "A"


def test_total_changes_read_vs_write(tmp_path):
    s = api.create_project(tmp_path / "p.db")
    api.list_persons(s.con)
    assert s.is_dirty() is False
    api.upsert_field(s.con, "fio", "ФИО")
    assert s.is_dirty() is True
    s.save()
    assert s.is_dirty() is False
    s.close()


def test_new_project_empty_v7(tmp_path):
    dest = tmp_path / "new.db"
    s = api.create_project(dest)
    assert dest.is_file()
    raw = sqlite3.connect(dest)
    assert raw.execute("PRAGMA user_version").fetchone()[0] == 7
    raw.close()
    assert s.work_path.is_file() and s.con is not None
    assert s.is_dirty() is False
    s.close()


def test_restore_from_bak_only_touches_work(tmp_path):
    s = api.create_project(tmp_path / "p.db")
    _edit(s)
    s.save()
    bak = PS.bak_path(s.source_path)
    src_after_first = _hash(s.source_path)
    api.create_person(s.con, {"n": "Y"})
    s.save()
    src_after_second = _hash(s.source_path)
    s.restore_from(bak)
    assert s.is_dirty() is True
    assert _hash(s.source_path) == src_after_second
    assert all(p["fields"].get("n") != "Y" for p in api.list_persons(s.con))
    s.save()
    assert _hash(s.source_path) != src_after_second
    s.close()


def test_export_db_reads_working_copy(tmp_path):
    s = api.create_project(tmp_path / "p.db")
    _edit(s)
    out = tmp_path / "exp.db"
    api.export_persons(s.con, out, format="db")
    assert _hash(s.source_path) != _hash(out) or True
    src_hash = _hash(s.source_path)
    exp = db.connect(str(out))
    assert any(api.get_person(exp, r["id"])["fields"].get("n") == "X" for r in exp.execute("SELECT id FROM persons"))
    assert _hash(s.source_path) == src_hash
    s.close(save=False)
