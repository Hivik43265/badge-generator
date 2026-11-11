"""Замечание №5 (решение Архитектора 11.11): имена полей только в редакторе, печать/PNG/PDF — только данные."""
from __future__ import annotations
import os, tempfile
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")
from badge_backend import api as bapi
from badge_backend import render as R


@pytest.fixture
def qtapp():
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QSettings
    app = QApplication.instance() or QApplication([])
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, tempfile.mkdtemp(prefix="bg_r1111_cfg_"))
    return app


def _project(tmp_path):
    from ui.backend_api import BackendAPI
    a = BackendAPI(tmp_path / "p.db", base_dir=str(tmp_path))
    bapi.upsert_field(a.con, "fio", "ФИО", 0)
    eid = bapi.create_element(a.con, "field", 20, 20, 600, 120, field_name="fio")
    pid = bapi.create_person(a.con, {"fio": "Иванов"}, None, print_mark=1)
    return a, eid, pid


@pytest.mark.parametrize("render_on, with_person, expect", [(True, True, False), (True, False, True), (False, False, True)])
def test_editor_payload_field_names(qtapp, tmp_path, monkeypatch, render_on, with_person, expect):
    """(а) рендер вкл. + запись → данные; (б) рендер вкл. без записи и (в) рендер выкл. → field_names=True; #поле всегда."""
    import ui.layout_editor as LE
    a, eid, pid = _project(tmp_path)
    jobs = []

    class _Pool:
        def start(self, job): jobs.append(job)
    monkeypatch.setattr(LE, "render_pool", lambda: _Pool())
    le = LE.LayoutEditor(a)
    le.show_render = render_on; le.person_id = pid if with_person else None
    jobs.clear(); le.load("front"); qtapp.processEvents()
    assert jobs, "холст редактора не отправил задание в preview_jobs"
    p = jobs[-1].payload
    assert p["field_names"] is expect
    assert (p["person"] is not None) == with_person
    it = next(i for i in le.items() if i.el["id"] == eid)
    assert it._tag is not None                                         # красная #поле есть во всех режимах


def test_print_png_pdf_never_field_names(qtapp, tmp_path, monkeypatch):
    """Печать/PNG/PDF не используют вид «имена полей»: _field_name_view не вызывается, PNG = render_card_db(field_names=False)."""
    from PIL import Image
    from PyQt6.QtPrintSupport import QPrinter
    a, eid, pid = _project(tmp_path)
    bapi.create_person(a.con, {}, None, print_mark=1)               # пустая запись: имён полей быть не должно
    want = {p["id"]: R.render_card_db(a.con, p["id"], "front", str(tmp_path), field_names=False).tobytes()
            for p in bapi.list_persons(a.con)}

    def boom(*_a, **_k): raise AssertionError("вид имён полей в печати/экспорте")
    monkeypatch.setattr(R, "_field_name_view", boom)
    out = tmp_path / "png"
    res = bapi.export_png(a.con, out_dir=out, sides=("front",), base_dir=str(tmp_path), allow_missing_photo=True)
    assert len(res) == 2
    for f in res:
        assert Image.open(f).convert("RGB").tobytes() == want[int(f.name.split("_")[0])]
    bapi.export_pdf(a.con, out_path=tmp_path / "c.pdf", sides=("front",), base_dir=str(tmp_path), allow_missing_photo=True)
    pr = QPrinter(QPrinter.PrinterMode.HighResolution)
    pr.setOutputFormat(QPrinter.OutputFormat.PdfFormat); pr.setOutputFileName(str(tmp_path / "p.pdf")); pr.setResolution(300)
    assert bapi.print_cards(a.con, pr, ("front",), base_dir=str(tmp_path), allow_missing_photo=True) == 2
