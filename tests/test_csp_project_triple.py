"""Новый формат проекта: тройка .csp + .csd + .db и открытие своего/чужого .csp."""
from pathlib import Path

import pytest

from badge_backend import api, db
from badge_backend.services.smartid_write import bundled_reference_csd


def _snap(con):
    rows = []
    for e in api.list_elements(con):
        rows.append((
            e["type"], e["x"], e["y"], e["w"], e["h"],
            e.get("field_name"), e.get("static_value"), e.get("side"),
            tuple(sorted((e.get("style") or {}).items())),
        ))
    return rows


def test_csp_project_triple(tmp_path):
    ref = bundled_reference_csd()
    assert ref is not None and ref.is_file()
    assert ref.name == "reference.csd"
    assert "assets" in ref.parts and "smartid" in ref.parts

    dest = tmp_path / "new" / "alpha.db"
    session = api.create_project(dest)
    try:
        assert dest.is_file()
        assert dest.with_suffix(".csp").is_file()
        assert dest.with_suffix(".csd").is_file()
        assert (dest.parent / "photos").is_dir()
        assert (dest.parent / "template_bg").is_dir()
        assert session.source_path == dest.resolve()
        assert session.csp_path is not None and session.csd_path is not None

        api.create_element(session.con, "text", 20, 20, 200, 40, static_value="Hello")
        api.create_element(session.con, "qr", 40, 80, 100, 100, static_value="qr-data")
        before = _snap(session.con)
        r = session.save()
        assert r["path"] == dest
        assert r["integrity"] == "ok"
        assert "dropped" in r
        assert any("qr" in str(x) for x in r["dropped"])
        assert session.last_save_dropped == r["dropped"]
        assert dest.with_suffix(".csd").is_file()
        assert dest.with_suffix(".csp").is_file()
    finally:
        session.discard()

    session2, result = api.open_csd_or_csp(dest.with_suffix(".csp"))
    try:
        assert result["kind"] == "own_project"
        assert session2.source_path == dest.resolve()
        assert session2.base_dir == dest.parent
        assert not str(session2.base_dir).startswith("/tmp") or dest.parent == session2.base_dir
        assert session2.import_source_paths == []
        assert _snap(session2.con) == before
        types = {e["type"] for e in api.list_elements(session2.con)}
        assert "qr" in types and "text" in types
    finally:
        session2.discard()

    sample = Path("/workspace/smartid_samples/license_to_firearms.csd")
    assert sample.is_file()
    imported, imp = api.import_smartid_as_new_project(sample)
    try:
        assert imp["kind"] == "import"
        assert imported.source_path is None
        assert imported.base_dir != sample.parent
        with pytest.raises(ValueError, match="Smart ID Designer"):
            imported.save_as(sample)
        out = tmp_path / "from_sid" / "copy.db"
        saved = imported.save_as(out)
        assert saved["path"] == out.resolve()
        assert out.is_file()
        assert out.with_suffix(".csp").is_file()
        assert out.with_suffix(".csd").is_file()
        assert saved.get("reference_csd") is not None
        assert Path(saved["reference_csd"]).resolve() == sample.resolve()
        assert "dropped" in saved
        with pytest.raises(ValueError, match="Smart ID Designer"):
            imported.save_as(sample)
    finally:
        imported.discard()

    old = tmp_path / "legacy" / "oldonly.db"
    old.parent.mkdir(parents=True)
    c = db.connect(str(old))
    api.create_element(c, "text", 11, 12, 30, 40, static_value="old")
    c.close()
    assert not old.with_suffix(".csp").exists()
    legacy = api.open_project(old)
    try:
        assert legacy.source_path == old.resolve()
        assert legacy.csp_path is None
        r = legacy.save()
        assert r.get("dropped") == []
        assert not old.with_suffix(".csp").exists()
        assert not old.with_suffix(".csd").exists()
        converted = tmp_path / "legacy" / "as_triple.db"
        r2 = legacy.save_as(converted)
        assert converted.is_file()
        assert converted.with_suffix(".csp").is_file()
        assert converted.with_suffix(".csd").is_file()
        assert "dropped" in r2
        assert r2.get("reference_csd") is not None
        assert Path(r2["reference_csd"]).resolve() == ref.resolve()
    finally:
        legacy.discard()
