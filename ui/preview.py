"""Предпросмотр: только результат рендера Backend (badge_backend.render)."""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLabel, QPushButton, QDoubleSpinBox
from .backend_api import BackendAPI


class PreviewWidget(QWidget):
    def __init__(self, api: BackendAPI, parent=None):
        super().__init__(parent)
        self.api = api
        self.person_box, self.side_box = QComboBox(), QComboBox()
        self.side_box.addItem("Лицевая", "front"); self.side_box.addItem("Оборотная", "back")
        self.scale = QDoubleSpinBox(); self.scale.setRange(0.1, 1.0); self.scale.setSingleStep(0.1); self.scale.setValue(0.8)
        refresh = QPushButton("Обновить"); refresh.clicked.connect(self.refresh)
        for w in (self.person_box, self.side_box): w.currentIndexChanged.connect(lambda _: self.render())
        self.scale.valueChanged.connect(lambda _: self.render())
        top = QHBoxLayout(); top.addWidget(QLabel("Запись:")); top.addWidget(self.person_box, 1)
        top.addWidget(QLabel("Сторона:")); top.addWidget(self.side_box)
        top.addWidget(QLabel("Масштаб:")); top.addWidget(self.scale); top.addWidget(refresh)
        self.image = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        lay = QVBoxLayout(self); lay.addLayout(top); lay.addWidget(self.image, 1)
        self.refresh()

    def refresh(self):
        cur = self.person_box.currentData()
        self.person_box.blockSignals(True); self.person_box.clear()
        self.person_box.addItem("(пустой шаблон)", None)
        for p in self.api.list_persons():
            f = p["fields"]
            self.person_box.addItem(f"#{p['id']} {f.get('last_name', '')} {f.get('first_name', '')}".strip(), p["id"])
        i = self.person_box.findData(cur)
        self.person_box.setCurrentIndex(i if (i > 0 or (i == 0 and cur is None and self.person_box.count() == 1)) else min(1, self.person_box.count() - 1))
        self.person_box.blockSignals(False)
        self.render()

    def render(self):
        try:
            img = self.api.render_preview(self.person_box.currentData(), self.side_box.currentData(), self.scale.value())
            self.image.setPixmap(QPixmap.fromImage(img))
        except Exception as e:  # noqa: BLE001
            self.image.setText(f"Ошибка рендера: {e}")
