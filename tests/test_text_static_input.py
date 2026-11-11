"""Поле «Текст» в панели «Свойства объекта»: многострочный static_value и двойной щелчок."""
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
    from ui.backend_api import BackendAPI
    from ui.layout_editor import LayoutEditor
    from ui.object_properties import ObjectPropertiesPanel

    api = BackendAPI(tmp_path / "p.db", base_dir=str(tmp_path))
    eid = api.create_element(type="text", x=20, y=20, w=400, h=200, static_value="Текст")
    le = LayoutEditor(api)
    op = ObjectPropertiesPanel(le)
    le.object_props = op
    le.show(); op.show(); qtapp.processEvents()
    le.select(eid); qtapp.processEvents()

    assert not op.row_text.isHidden() and op.w_text.isVisible()
    assert op.row_static.isHidden()
    op.w_text.setPlainText("Первая\nВторая")
    op._text_timer.stop(); op._text_timer.timeout.emit()
    qtapp.processEvents()

    stored = next(e for e in api.list_elements() if e["id"] == eid)["static_value"]
    assert stored == "Первая\nВторая"

    it = next(i for i in le.items() if i.el["id"] == eid)
    # Как cycle_select_at: без синтетической мыши вызываем тот же обработчик, что и двойной щелчок.
    le._focus_text_prop(it)
    qtapp.processEvents()
    assert op.w_text.hasFocus()

    le.close(); op.close(); api.close()
