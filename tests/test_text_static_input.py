"""Поле «Текст» в свойствах объекта: многострочный static_value и двойной щелчок."""
from __future__ import annotations
import os, tempfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6")


@pytest.fixture
def qtapp():
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QSettings
    app = QApplication.instance() or QApplication([])
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope,
                      tempfile.mkdtemp(prefix="bg_text_static_cfg_"))
    return app


def test_text_static_multiline_and_double_click(qtapp, tmp_path):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from ui.backend_api import BackendAPI
    from ui.layout_editor import LayoutEditor

    api = BackendAPI(tmp_path / "p.db", base_dir=str(tmp_path))
    eid = api.create_element(type="text", x=20, y=20, w=400, h=200, static_value="Текст")
    le = LayoutEditor(api)
    le.show(); qtapp.processEvents()
    le.select(eid); qtapp.processEvents()

    assert le.p_text.isVisible() and not le.p_static.isVisible()
    le.p_text.setPlainText("Первая\nВторая")
    le._text_timer.stop(); le._text_timer.timeout.emit()
    qtapp.processEvents()

    stored = next(e for e in api.list_elements() if e["id"] == eid)["static_value"]
    assert stored == "Первая\nВторая"

    it = next(i for i in le.items() if i.el["id"] == eid)
    pos = le.view.mapFromScene(it.sceneBoundingRect().center())
    QTest.mouseDClick(le.view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    qtapp.processEvents()
    assert le.p_text.hasFocus()
    assert le.p_text.textCursor().hasSelection()

    le.close(); api.close()
