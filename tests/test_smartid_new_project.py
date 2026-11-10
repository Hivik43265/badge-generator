"""Открытие Smart ID (.csd/.csp) как нового несохранённого проекта."""
import importlib.util
from pathlib import Path

import pytest

from badge_backend import api

_spec = importlib.util.spec_from_file_location(
    "_smartid_helpers", Path(__file__).resolve().parent / "test_smartid.py")
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
_build_csd = _helpers._build_csd


def _sample_csd(tmp_path, name="license.csd"):
    src = tmp_path / name
    src.write_bytes(_build_csd())
    return src


def test_import_csd_as_new_unsaved_project(tmp_path):
    src = _sample_csd(tmp_path, "license_to_firearms.csd")
    before = {p.name for p in tmp_path.iterdir()}
    session, result = api.import_smartid_as_new_project(src)
    try:
        assert session.source_path is None
        assert session.suggested_name == "license_to_firearms.db"
        assert session.base_dir.is_dir()
        assert session.base_dir != src.parent
        assert (session.base_dir / "template_bg").is_dir()
        assert result["persons_imported"] == 0
        assert api.list_persons(session.con) == []
        els = api.list_elements(session.con)
        types = {e["type"] for e in els}
        assert {"field", "text", "photo", "image", "rect"} <= types
        assert {p.name for p in tmp_path.iterdir()} == before
        assert src.read_bytes()  # исходник не тронут
    finally:
        session.discard()
    assert not session.base_dir.exists()


def test_save_as_refuses_source_csd(tmp_path):
    src = _sample_csd(tmp_path)
    session, _ = api.import_smartid_as_new_project(src)
    try:
        with pytest.raises(ValueError, match="нельзя сохранить проект поверх исходного файла Smart ID Designer"):
            session.save_as(src)
        with pytest.raises(ValueError, match=r"\.csp, \.csd или его базы данных"):
            session.save_as(src)
        dest = tmp_path / "out" / "проект.db"
        r = session.save_as(dest)
        assert r["path"] == dest.resolve()
        assert session.source_path == dest.resolve()
        assert (dest.parent / "template_bg").is_dir()
        assert any((dest.parent / "template_bg").iterdir())
        assert session.con is not None
        assert api.list_elements(session.con)
    finally:
        session.discard()


def test_save_as_refuses_csp_and_database(tmp_path):
    csd = _sample_csd(tmp_path, "card.csd")
    dbp = tmp_path / "people.db"
    import sqlite3
    src = sqlite3.connect(str(dbp))
    src.execute("CREATE TABLE Employees (fio TEXT)")
    src.execute("INSERT INTO Employees VALUES ('Иванов')")
    src.commit()
    src.close()
    csp = tmp_path / "proj.csp"
    csp.write_text(
        "\n".join([
            "[DB]",
            "CSD_Name=card.csd",
            f"SQLiteDBPath={tmp_path}",
            "SQLiteDBName=people.db",
            "TableName=Employees",
            "[BIND]",
            "CSD_Fields=Name",
            "TBL_Fields=fio",
        ]),
        encoding="utf-8",
    )
    session, result = api.import_smartid_as_new_project(csp)
    try:
        assert result["persons_imported"] == 1
        for blocked in (csp, csd, dbp):
            with pytest.raises(ValueError, match="Smart ID Designer"):
                session.save_as(blocked)
    finally:
        session.discard()


def test_missing_csd_lists_all_searched_paths(tmp_path):
    csp = tmp_path / "proj.csp"
    csp.write_text(
        "\n".join([
            "[DB]",
            "CSD_Name=missing.csd",
            "SQLiteDBName=people.db",
        ]),
        encoding="utf-8",
    )
    with pytest.raises(FileNotFoundError) as ei:
        api.import_smartid_as_new_project(csp)
    msg = str(ei.value)
    assert "Не найден файл макета (.csd) для проекта proj.csp." in msg
    assert "Искали по путям:" in msg
    assert "missing.csd" in msg
    assert str(csp.with_suffix(".csd")) in msg or "proj.csd" in msg


def test_missing_database_lists_all_searched_paths(tmp_path):
    csd = _sample_csd(tmp_path, "card.csd")
    csp = tmp_path / "proj.csp"
    csp.write_text(
        "\n".join([
            "[DB]",
            "CSD_Name=card.csd",
            "SQLiteDBPath=data",
            "SQLiteDBName=people.db",
            "TableName=Employees",
        ]),
        encoding="utf-8",
    )
    with pytest.raises(FileNotFoundError) as ei:
        api.import_smartid_as_new_project(csp)
    msg = str(ei.value)
    assert "Не найдена база данных записей для проекта proj.csp." in msg
    assert "Искали по путям:" in msg
    assert "people.db" in msg
    assert "data" in msg
    assert csd.is_file()


def test_adopt_session_does_not_persist_previous(tmp_path):
    from ui.backend_api import BackendAPI

    db = tmp_path / "proj.db"
    sess = api.create_project(db)
    api.upsert_field(sess.con, "n", "N", 0)
    api.create_person(sess.con, {"n": "saved"})
    sess.save()
    before = db.read_bytes()
    api.create_person(sess.con, {"n": "dirty"})
    assert sess.is_dirty()

    wrapper = BackendAPI(":memory:")
    try:
        wrapper.adopt_session(sess)
        wrapper.open_db(":memory:")
        assert db.read_bytes() == before
        names = {p["fields"].get("n") for p in api.list_persons(api.connect(str(db)))}
        assert names == {"saved"}
    finally:
        wrapper.close()


def test_backend_api_facade_adopts_session(tmp_path):
    from ui.backend_api import BackendAPI

    src = _sample_csd(tmp_path, "badge.csd")
    wrapper = BackendAPI(":memory:")
    try:
        session, result = wrapper.import_smartid_as_new_project(src)
        assert wrapper.session is session
        assert wrapper.con is session.con
        assert session.source_path is None
        assert Path(wrapper.db_path).name == "badge.db"
        assert result["persons_imported"] == 0
        assert wrapper.list_elements()
    finally:
        wrapper.close()
