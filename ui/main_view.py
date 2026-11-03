"""Главный вид: собственные простые иконки, панель «Предпросмотр / Поля», диалоги
«Очередь печати», «Положение», «Настройка», «Захват изображения».
Весь рендер — только через Backend (render_card); SQL нет."""
import os
from PyQt6.QtCore import Qt, QPointF, QRectF, QSize
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QBrush, QPolygonF, QFont
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget, QListWidget, QListWidgetItem,
                             QTableWidget, QTableWidgetItem, QHeaderView, QDialog, QDialogButtonBox, QFormLayout,
                             QLineEdit, QPushButton, QSpinBox, QGridLayout, QFileDialog, QSplitter, QSizePolicy,
                             QAbstractItemView, QDoubleSpinBox, QMessageBox)
from .backend_api import BackendAPI, CARD_W_PX, CARD_H_PX
from .layout_editor import element_caption
from .records_table import format_printed_at

ACCENT, INK = QColor("#2B6CB0"), QColor("#2D3748")


def make_icon(kind: str, size: int = 32) -> QIcon:
    """Простые собственные пиктограммы (геометрия QPainter)."""
    pm = QPixmap(size, size); pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 32.0; p.scale(s, s)
    pen = QPen(INK, 2); p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
    A = QBrush(ACCENT)
    def cyl(fill):
        p.setBrush(fill); p.drawRect(7, 8, 18, 16); p.drawEllipse(7, 4, 18, 8); p.drawArc(7, 20, 18, 8, 180 * 16, 180 * 16)
    if kind == "connect":
        cyl(QBrush(QColor("#C6F6D5"))); p.setPen(QPen(QColor("#2F855A"), 3)); p.drawLine(13, 16, 16, 19); p.drawLine(16, 19, 22, 12)
    elif kind == "disconnect":
        cyl(QBrush(QColor("#FED7D7"))); p.setPen(QPen(QColor("#C53030"), 3)); p.drawLine(12, 12, 20, 20); p.drawLine(20, 12, 12, 20)
    elif kind == "settings":
        p.setBrush(A); p.drawEllipse(9, 9, 14, 14); p.setBrush(QBrush(Qt.GlobalColor.white)); p.drawEllipse(13, 13, 6, 6)
        for a in range(0, 360, 45):
            p.save(); p.translate(16, 16); p.rotate(a); p.setBrush(A); p.drawRect(-2, -14, 4, 5); p.restore()
    elif kind == "save":
        p.setBrush(A); p.drawRoundedRect(5, 5, 22, 22, 3, 3); p.setBrush(QBrush(Qt.GlobalColor.white))
        p.drawRect(10, 5, 12, 8); p.drawRect(9, 17, 14, 10)
    elif kind == "print":
        p.setBrush(QBrush(QColor("#E2E8F0"))); p.drawRect(9, 4, 14, 8); p.setBrush(A); p.drawRoundedRect(4, 11, 24, 11, 2, 2)
        p.setBrush(QBrush(Qt.GlobalColor.white)); p.drawRect(9, 18, 14, 10)
    elif kind == "queue":
        for i, y in enumerate((7, 15, 23)):
            p.setBrush(A if i == 0 else QBrush(QColor("#BEE3F8"))); p.drawRect(4, y - 3, 6, 6); p.drawLine(13, y, 28, y)
    elif kind == "printed":
        p.setBrush(QBrush(QColor("#E2E8F0"))); p.drawRect(6, 4, 20, 24)
        p.setPen(QPen(QColor("#2F855A"), 3)); p.drawLine(10, 17, 14, 21); p.drawLine(14, 21, 22, 11)
    elif kind in ("front", "back"):
        p.setBrush(QBrush(QColor("#EDF2F7") if kind == "back" else A)); p.drawRoundedRect(3, 8, 26, 17, 3, 3)
        p.setPen(QPen(Qt.GlobalColor.white if kind == "front" else INK, 2))
        if kind == "front": p.drawEllipse(7, 12, 7, 9); p.drawLine(17, 14, 25, 14); p.drawLine(17, 19, 23, 19)
        else: p.drawLine(7, 13, 25, 13); p.drawLine(7, 17, 25, 17); p.drawLine(7, 21, 18, 21)
    elif kind == "text":
        f = QFont(); f.setBold(True); f.setPixelSize(24); p.setFont(f); p.setPen(QPen(ACCENT)); p.drawText(QRectF(0, 0, 32, 32), Qt.AlignmentFlag.AlignCenter, "Т")
    elif kind == "position":
        p.drawRect(5, 5, 22, 22); p.setBrush(A); p.drawRect(12, 12, 8, 8)
        p.drawLine(16, 2, 16, 8); p.drawLine(16, 24, 16, 30); p.drawLine(2, 16, 8, 16); p.drawLine(24, 16, 30, 16)
    elif kind == "add":
        p.setBrush(A); p.drawEllipse(4, 4, 24, 24); p.setPen(QPen(Qt.GlobalColor.white, 3)); p.drawLine(16, 9, 16, 23); p.drawLine(9, 16, 23, 16)
    elif kind == "remove":
        p.setBrush(QBrush(QColor("#E53E3E"))); p.drawEllipse(4, 4, 24, 24); p.setPen(QPen(Qt.GlobalColor.white, 3)); p.drawLine(9, 16, 23, 16)
    elif kind == "capture":
        p.setBrush(A); p.drawRoundedRect(3, 9, 26, 18, 3, 3); p.drawRect(11, 5, 10, 5)
        p.setBrush(QBrush(Qt.GlobalColor.white)); p.drawEllipse(10, 12, 12, 12)
    elif kind == "design":
        p.setBrush(QBrush(QColor("#EDF2F7"))); p.drawRect(4, 6, 24, 20); p.setBrush(A)
        p.drawPolygon(QPolygonF([QPointF(10, 22), QPointF(24, 8), QPointF(27, 11), QPointF(13, 25)]))
    else:
        p.setBrush(A); p.drawEllipse(8, 8, 16, 16)
    p.end()
    return QIcon(pm)


class PreviewPanel(QWidget):
    """Правая часть главного вида: сверху — лицевая сторона выбранной записи (render_card),
    ниже — вкладки «Поля макета» / «Поля БД»."""

    def __init__(self, api: BackendAPI, parent=None):
        super().__init__(parent)
        self.api, self.person_id, self.side = api, None, "front"
        self.title = QLabel("Предпросмотр / Поля"); self.title.setStyleSheet("font-weight:600; font-size:13px;")
        self.image = QLabel(); self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setMinimumSize(320, 202); self.image.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.image.setStyleSheet("background:#EDF2F7; border:1px solid #CBD5E0; border-radius:6px;")
        self.caption = QLabel(); self.caption.setStyleSheet("color:#4A5568;")
        self.tabs = QTabWidget()
        self.layout_fields = QListWidget()
        self.db_fields = QTableWidget(0, 2); self.db_fields.setHorizontalHeaderLabels(["Поле", "Значение"])
        self.db_fields.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.db_fields.verticalHeader().setVisible(False)
        self.db_fields.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # QTabWidget над предпросмотром: на каждой вкладке сверху общий предпросмотр, снизу — свой список
        self.preview_box = QWidget(); pv = QVBoxLayout(self.preview_box); pv.setContentsMargins(0, 0, 0, 0)
        pv.addWidget(self.image, 1); pv.addWidget(self.caption)
        self.pages = []
        for content, name in ((self.layout_fields, "Поля макета"), (self.db_fields, "Поля БД")):
            pg = QWidget(); QVBoxLayout(pg).setContentsMargins(4, 4, 4, 4); pg.layout().addWidget(content, 2)
            self.tabs.addTab(pg, name); self.pages.append(pg)
        self.tabs.currentChanged.connect(self._move_preview); self._move_preview(0)
        lay = QVBoxLayout(self); lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(self.title); lay.addWidget(self.tabs, 1)
        self.pixmap = None

    def _move_preview(self, i):
        self.pages[i].layout().insertWidget(0, self.preview_box, 3); self.preview_box.show(); self._fit()

    def set_side(self, side):
        self.side = side; self.refresh()

    def set_person(self, pid):
        self.person_id = pid; self.refresh()

    def refresh(self):
        p = self.api.get_person(self.person_id) if self.person_id is not None else None
        if p is None: self.person_id = None
        img = self.api.render_card(self.person_id, self.side)          # рендер Backend
        self.pixmap = QPixmap.fromImage(img)
        self._fit()
        side = "лицевая" if self.side == "front" else "оборот"
        self.caption.setText(f"{'Запись #' + str(p['id']) if p else 'Пустой шаблон'} · {side}")
        # Поля макета
        labels = {f["name"]: f["label"] for f in self.api.list_fields()}
        self.layout_fields.clear()
        for e in self.api.list_elements(self.side):
            it = QListWidgetItem(element_caption(e, labels)); it.setData(Qt.ItemDataRole.UserRole, e["id"])
            self.layout_fields.addItem(it)
        if not self.layout_fields.count():
            self.layout_fields.addItem("Шаблон пуст — откройте «Дизайн → Редактор макета»")
        # Поля БД
        rows = []
        if p:
            logo = next((e.get("static_value") for e in sorted(self.api.list_elements(), key=lambda e: e["side"] != "front") if e["type"] == "image"), None)
            if p["fields"].get("logo") or logo: rows.append(("Логотип", p["fields"].get("logo") or logo))
            rows.append(("Фото", p.get("photo_path") or "—"))
            fio = " ".join(str(p["fields"].get(k) or "") for k in ("last_name", "first_name", "middle_name")).strip()
            if fio: rows.append(("ФИО", fio))
            for f in self.api.list_fields():
                if f["name"] != "logo": rows.append((f["label"], str(p["fields"].get(f["name"], "") or "")))
            rows.append(("Напечатано", format_printed_at(p.get("printed_at")) or "—"))
        self.db_fields.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            self.db_fields.setItem(r, 0, QTableWidgetItem(k)); self.db_fields.setItem(r, 1, QTableWidgetItem(v))

    def _fit(self):
        if getattr(self, "pixmap", None) is None: return
        w = max(200, self.image.width() - 12); h = max(120, self.image.height() - 12)
        self.image.setPixmap(self.pixmap.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, ev):
        super().resizeEvent(ev); self._fit()

    def db_rows(self):
        return [(self.db_fields.item(r, 0).text(), self.db_fields.item(r, 1).text()) for r in range(self.db_fields.rowCount())]


class PrintQueueDialog(QDialog):
    """Очередь печати: записи с print_mark=1."""

    def __init__(self, api: BackendAPI, parent=None, on_print=None):
        super().__init__(parent); self.setWindowTitle("Очередь печати"); self.resize(560, 380)
        self.api, self.on_print = api, on_print
        self.table = QTableWidget(0, 4); self.table.setHorizontalHeaderLabels(["#", "ФИО", "Должность", "Напечатано"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.table.verticalHeader().setVisible(False)
        self.info = QLabel()
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close); bb.rejected.connect(self.reject)
        self.btn_print = bb.addButton("Печать…", QDialogButtonBox.ButtonRole.ActionRole)
        self.btn_print.clicked.connect(self._print)
        self.btn_clear = bb.addButton("Убрать из очереди", QDialogButtonBox.ButtonRole.ActionRole)
        self.btn_clear.clicked.connect(self._unmark)
        lay = QVBoxLayout(self); lay.addWidget(self.table); lay.addWidget(self.info); lay.addWidget(bb)
        self.reload()

    def reload(self):
        self.persons = self.api.list_persons(only_marked=True)
        self.table.setRowCount(len(self.persons))
        for r, p in enumerate(self.persons):
            f = p["fields"]
            vals = [str(p["id"]), " ".join(str(f.get(k) or "") for k in ("last_name", "first_name", "middle_name")).strip(),
                    str(f.get("position") or ""), format_printed_at(p.get("printed_at"))]
            for c, v in enumerate(vals): self.table.setItem(r, c, QTableWidgetItem(v))
        self.info.setText(f"В очереди: {len(self.persons)}" if self.persons else "Очередь пуста — отметьте записи в колонке «Печать».")
        self.btn_print.setEnabled(bool(self.persons))

    def ids(self):
        return [p["id"] for p in self.persons]

    def _unmark(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        ids = [self.persons[r]["id"] for r in rows] or self.ids()
        self.api.set_print_mark(ids, False); self.reload()

    def _print(self):
        if self.on_print: self.accept(); self.on_print()


ALIGN = [("left", "По левому краю"), ("hcenter", "По центру (гориз.)"), ("right", "По правому краю"),
         ("top", "По верху"), ("vcenter", "По центру (верт.)"), ("bottom", "По низу")]


def aligned_geometry(el, how, margin=0):
    x, y, w, h = el["x"], el["y"], el["w"], el["h"]
    bw, bh = abs(w), abs(h); ox, oy = min(0, w), min(0, h)          # линии: w/h могут быть < 0
    if how == "left": x = margin - ox
    elif how == "right": x = CARD_W_PX - margin - bw - ox
    elif how == "hcenter": x = (CARD_W_PX - bw) // 2 - ox
    elif how == "top": y = margin - oy
    elif how == "bottom": y = CARD_H_PX - margin - bh - oy
    elif how == "vcenter": y = (CARD_H_PX - bh) // 2 - oy
    return {"x": int(x), "y": int(y)}


class PositionDialog(QDialog):
    """Положение выбранного элемента: X/Y и выравнивание по карте."""

    def __init__(self, el, parent=None):
        super().__init__(parent); self.setWindowTitle("Положение элемента"); self.el = dict(el)
        self.x = QSpinBox(); self.y = QSpinBox()
        for s_, v in ((self.x, el["x"]), (self.y, el["y"])): s_.setRange(-2000, 2000); s_.setValue(v)
        self.margin = QSpinBox(); self.margin.setRange(0, 300); self.margin.setValue(20)
        form = QFormLayout(); form.addRow("X, px:", self.x); form.addRow("Y, px:", self.y); form.addRow("Отступ от края, px:", self.margin)
        grid = QGridLayout()
        for i, (k, t) in enumerate(ALIGN):
            b = QPushButton(t); b.clicked.connect(lambda _=False, k=k: self.align(k)); grid.addWidget(b, i // 3, i % 3)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self); lay.addWidget(QLabel(element_caption(el))); lay.addLayout(form); lay.addLayout(grid); lay.addWidget(bb)

    def align(self, how):
        g = aligned_geometry({**self.el, "x": self.x.value(), "y": self.y.value()}, how, self.margin.value())
        self.x.setValue(g["x"]); self.y.setValue(g["y"])

    def value(self):
        return {"x": self.x.value(), "y": self.y.value()}


class SettingsDialog(QDialog):
    """Настройка: каталог фото/изображений (база относительных путей) и масштаб предпросмотра."""

    def __init__(self, api: BackendAPI, settings, parent=None):
        super().__init__(parent); self.setWindowTitle("Настройка"); self.api, self.settings = api, settings
        self.base_dir = QLineEdit(str(api.base_dir or "")); pick = QPushButton("…")
        pick.clicked.connect(lambda: (lambda d: d and self.base_dir.setText(d))(QFileDialog.getExistingDirectory(self, "Каталог фото", self.base_dir.text())))
        row = QHBoxLayout(); row.addWidget(self.base_dir, 1); row.addWidget(pick)
        self.grid = QSpinBox(); self.grid.setRange(5, 200); self.grid.setValue(int(settings.value("editor/grid", 20)))
        form = QFormLayout(); form.addRow("Каталог фото и изображений:", row); form.addRow("Шаг сетки редактора, px:", self.grid)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self); lay.addLayout(form); lay.addWidget(bb)

    def apply(self):
        if self.base_dir.text().strip(): self.api.base_dir = self.base_dir.text().strip()
        self.settings.setValue("editor/grid", self.grid.value())
        return {"base_dir": self.api.base_dir, "grid": self.grid.value()}


def camera_available():
    """Камера — только если установлен QtMultimedia и есть устройство; иначе захват из файла."""
    try:
        from PyQt6.QtMultimedia import QMediaDevices
    except Exception:  # noqa: BLE001
        return False
    try:
        return bool(QMediaDevices.videoInputs())
    except Exception:  # noqa: BLE001
        return False


class CameraDialog(QDialog):
    """Снимок с веб-камеры (QtMultimedia). Создаётся только если camera_available()."""

    def __init__(self, target_path, parent=None):
        from PyQt6.QtMultimedia import QCamera, QMediaCaptureSession, QImageCapture
        from PyQt6.QtMultimediaWidgets import QVideoWidget
        super().__init__(parent); self.setWindowTitle("Захват изображения"); self.path = None; self.target = target_path
        self.cam = QCamera(); self.session = QMediaCaptureSession(); self.cap = QImageCapture()
        self.video = QVideoWidget(); self.session.setCamera(self.cam); self.session.setImageCapture(self.cap)
        self.session.setVideoOutput(self.video)
        self.cap.imageCaptured.connect(self._got)
        shot = QPushButton("Сделать снимок"); shot.clicked.connect(lambda: self.cap.capture())
        lay = QVBoxLayout(self); lay.addWidget(self.video, 1); lay.addWidget(shot); self.resize(640, 520)
        self.cam.start()

    def _got(self, _id, image):
        image.save(self.target); self.path = self.target; self.cam.stop(); self.accept()
