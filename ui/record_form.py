"""Форма записи: поля из person_fields + настройки фото (photo_config) с живым превью от Backend."""
import os
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QDialog, QFormLayout, QLineEdit, QGroupBox, QPushButton, QSpinBox,
                             QDoubleSpinBox, QLabel, QDialogButtonBox, QVBoxLayout, QHBoxLayout,
                             QFileDialog, QCheckBox, QComboBox, QMessageBox)
from .backend_api import BackendAPI, PhotoConfig, DEFAULT_PHOTO_CONFIG


class RecordForm(QDialog):
    def __init__(self, api: BackendAPI, person_id=None, parent=None):
        super().__init__(parent)
        self.api, self.person_id = api, person_id
        p = api.get_person(person_id) if person_id else None
        self.person = p or {"id": None, "fields": {}, "photo_path": None,
                            "photo_config": DEFAULT_PHOTO_CONFIG, "print_mark": 0}
        self.setWindowTitle(f"Запись #{person_id}" if p else "Новая запись")
        fields = api.list_fields()
        self._new_fields = []
        if not fields:  # пустая БД: стандартные поля, создаются через upsert_field при сохранении
            from .backend_api import LABELS
            fields = [{"name": k, "label": v, "sort_order": i} for i, (k, v) in
                      enumerate(list(LABELS.items())[:5])]
            self._new_fields = fields
        form = QFormLayout(); self.edits = {}
        for f in fields:
            e = QLineEdit(str(self.person["fields"].get(f["name"], "")))
            self.edits[f["name"]] = e; form.addRow(f["label"] + ":", e)

        cfg = PhotoConfig.parse(self.person["photo_config"])
        box = QGroupBox("Фото"); pf = QFormLayout(box)
        self.photo_path = QLineEdit(self.person["photo_path"] or ""); self.photo_path.setReadOnly(True)
        load = QPushButton("Загрузить фото…"); load.clicked.connect(self._load_photo)
        ph = QHBoxLayout(); ph.addWidget(self.photo_path, 1); ph.addWidget(load)
        pf.addRow("Файл:", ph)

        def spin(v, lo=-3000, hi=3000):
            s = QSpinBox(); s.setRange(lo, hi); s.setSuffix(" px"); s.setValue(v); return s
        self.sx, self.sy = spin(cfg.x), spin(cfg.y)
        self.cx, self.cy = spin(cfg.crop_x, 0, 20000), spin(cfg.crop_y, 0, 20000)
        self.scale = QDoubleSpinBox(); self.scale.setRange(0.05, 20); self.scale.setSingleStep(0.05)
        self.scale.setDecimals(2); self.scale.setValue(cfg.scale)
        self.angle = QDoubleSpinBox(); self.angle.setRange(-360, 360); self.angle.setSuffix("°"); self.angle.setValue(cfg.angle)
        row = lambda a, b: (lambda l: (l.addWidget(a), l.addWidget(b), l)[-1])(QHBoxLayout())
        pf.addRow("Масштаб:", self.scale); pf.addRow("Смещение X/Y:", row(self.sx, self.sy))
        pf.addRow("Обрезка X/Y (исходник):", row(self.cx, self.cy)); pf.addRow("Поворот (по часовой):", self.angle)
        reset = QPushButton("Сбросить настройки фото"); reset.clicked.connect(self._reset_cfg); pf.addRow(reset)

        self.side = QComboBox(); self.side.addItem("Лицевая", "front"); self.side.addItem("Оборотная", "back")
        self.preview = QLabel(alignment=Qt.AlignmentFlag.AlignCenter); self.preview.setMinimumSize(506, 319)
        self.preview.setStyleSheet("border:1px solid #aaa;")
        pv = QVBoxLayout(); pv.addWidget(QLabel("Превью (рендер Backend):")); pv.addWidget(self.side); pv.addWidget(self.preview); pv.addStretch()

        self._timer = QTimer(self, singleShot=True, interval=150, timeout=self.update_preview)
        for w in (self.sx, self.sy, self.cx, self.cy): w.valueChanged.connect(lambda *_: self._timer.start())
        for w in (self.scale, self.angle): w.valueChanged.connect(lambda *_: self._timer.start())
        for e in self.edits.values(): e.textChanged.connect(lambda *_: self._timer.start())
        self.side.currentIndexChanged.connect(lambda *_: self.update_preview())

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        bb.accepted.connect(self.save); bb.rejected.connect(self.reject)
        left = QVBoxLayout(); left.addLayout(form); left.addWidget(box); left.addStretch()
        main = QHBoxLayout(); main.addLayout(left); main.addLayout(pv)
        lay = QVBoxLayout(self); lay.addLayout(main); lay.addWidget(bb)
        self.update_preview()

    def config_string(self) -> str:
        return PhotoConfig(self.sx.value(), self.sy.value(), self.scale.value(),
                           self.cx.value(), self.cy.value(), self.angle.value()).dump()

    def _reset_cfg(self):
        c = PhotoConfig.parse(DEFAULT_PHOTO_CONFIG)
        for w, v in ((self.sx, c.x), (self.sy, c.y), (self.scale, c.scale), (self.cx, c.crop_x),
                     (self.cy, c.crop_y), (self.angle, c.angle)): w.setValue(v)

    def _load_photo(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выбор фото", self.api.base_dir, "Изображения (*.png *.jpg *.jpeg *.bmp)")
        if path:
            try:
                rel = os.path.relpath(path, self.api.base_dir)
                path = path if rel.startswith("..") else rel   # README: photo_path относительно base_dir
            except ValueError:
                pass
            self.photo_path.setText(path); self.update_preview()

    def draft_person(self) -> dict:
        """Несохранённое состояние формы для превью (рендерит Backend)."""
        import json
        fields = {**self.person["fields"], **{n: e.text().strip() for n, e in self.edits.items()}}
        return {"id": self.person["id"], "fields_json": json.dumps(fields, ensure_ascii=False),
                "photo_path": self.photo_path.text() or None, "photo_config": self.config_string()}

    def update_preview(self):
        try:
            img = self.api.render_preview(self.draft_person(), self.side.currentData(), 0.5)
            self.preview.setPixmap(QPixmap.fromImage(img))
        except Exception as e:  # noqa: BLE001
            self.preview.setText(f"Ошибка рендера: {e}")

    def save(self):
        fields = {n: e.text().strip() for n, e in self.edits.items()}
        photo = self.photo_path.text() or None
        try:
            for f in self._new_fields:
                self.api.upsert_field(f["name"], f["label"], f["sort_order"])
            if self.person_id:
                self.api.update_person(self.person_id, fields=fields, photo_path=photo)
            else:
                self.person_id = self.api.create_person(fields, photo, None, 0)
            self.api.update_photo_config(self.person_id, self.config_string())   # только эта запись
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Ошибка сохранения", str(e)); return
        self.accept()
