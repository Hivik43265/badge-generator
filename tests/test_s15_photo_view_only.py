"""stage-15 spec 6: «Применить» в редакторе фото сохраняет только вид (set_photo_view), без нового JPEG."""
from __future__ import annotations
import os, shutil, tempfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6")


@pytest.fixture
def qtapp():
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QSettings
    app = QApplication.instance() or QApplication([])
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope,
                      tempfile.mkdtemp(prefix="bg_s15_pv_cfg_"))
    return app


def _spin(ms=50):
    from PyQt6.QtCore import QEventLoop, QTimer
    loop = QEventLoop(); QTimer.singleShot(ms, loop.quit); loop.exec()


def _project(tmp: Path):
    from ui.backend_api import BackendAPI
    api = BackendAPI(tmp / "p.db", base_dir=str(tmp))
    api.upsert_field("foto", "Фото", 0, data_type="image")
    eid = api.create_element(type="photo", x=0, y=0, w=300, h=400)
    api.link_field(eid, "foto")
    return api, eid


def test_apply_existing_record_view_only_no_new_file(qtapp, tmp_path):
    """Существующая запись: Apply → set_photo_view, путь не меняется, photos/ без нового файла; reopen — те же params."""
    from ui.photo_editor import PhotoEditor
    face = Path(__file__).resolve().parent / "fixtures" / "face_astronaut.jpg"
    assert face.is_file()
    api, eid = _project(tmp_path)
    rel = api.save_photo(face.read_bytes(), ext="jpg")
    pid = api.create_person({"foto": rel})
    photos0 = set((tmp_path / "photos").glob("*"))
    ed = PhotoEditor(str(tmp_path / rel), api, None, field_name="foto", person_id=pid, element_id=eid)
    ed.show(); _spin(80)
    ed.sl["brightness"].setValue(18); ed.sl["contrast"].setValue(8); ed.update_preview()
    assert ed.apply() is True and ed.applied and ed.result_path is None
    assert set((tmp_path / "photos").glob("*")) == photos0
    assert api.get_person(pid)["fields"]["foto"] == rel
    view = api.get_photo_view(pid, "foto")
    assert view["brightness"] == 18 and view["contrast"] == 8
    # reopen
    ed2 = PhotoEditor(str(tmp_path / rel), api, None, field_name="foto", person_id=pid, element_id=eid)
    ed2.show(); _spin(80)
    assert ed2.sp["brightness"].value() == 18 and ed2.sp["contrast"].value() == 8
    ed2.reject(); ed.reject(); api.close()


def test_apply_new_record_pending_view_on_save(qtapp, tmp_path):
    """Новая запись: Apply копит view; после «Сохранить» формы — set_photo_view; путь = исходник, без лишнего JPEG."""
    from PyQt6.QtTest import QTest
    from PyQt6.QtCore import Qt
    from ui.photo_editor import PhotoEditor
    from ui.record_form import RecordForm
    from ui import photo_editor as pe
    from ui.main_window import MainWindow
    face = Path(__file__).resolve().parent / "fixtures" / "face_astronaut.jpg"
    api, eid = _project(tmp_path)
    w = MainWindow(api)
    src = tmp_path / "src.jpg"; shutil.copy(face, src)
    rf = RecordForm(api, None, w); rf.show(); _spin(40)
    ie = rf.edits["foto"]; assert ie.from_file(str(src))
    path0 = ie.text(); assert path0.startswith("photos/")
    photos0 = set((tmp_path / "photos").glob("*"))
    got = []
    pe.editor_hook = lambda d: got.append(d) or 0
    try:
        QTest.mouseDClick(ie.still, Qt.MouseButton.LeftButton); _spin(40)
    finally:
        pe.editor_hook = None
    ed = got[-1]
    ed.sl["brightness"].setValue(22); ed.sl["contrast"].setValue(5); ed.update_preview()
    assert ed.apply() is True and ed.person_id is None and ed.result_path is None
    assert ie.pending_view and ie.pending_view["brightness"] == 22
    assert ie.text() == path0
    assert set((tmp_path / "photos").glob("*")) == photos0
    assert rf.save() is not False
    pid = api.list_persons()[-1]["id"]
    assert api.get_person(pid)["fields"]["foto"] == path0
    assert api.get_photo_view(pid, "foto")["brightness"] == 22
    assert api.get_photo_view(pid, "foto")["contrast"] == 5
    # reopen editor — те же params
    ed2 = PhotoEditor(str(tmp_path / path0), api, None, field_name="foto", person_id=pid, element_id=eid)
    ed2.show(); _spin(80)
    assert ed2.sp["brightness"].value() == 22 and ed2.sp["contrast"].value() == 5
    ed2.reject(); w.close(); api.close()
