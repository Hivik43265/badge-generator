import os
from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtWidgets import (QMainWindow, QTabWidget, QFileDialog, QMessageBox, QInputDialog, QSplitter, QMenu,
                             QToolButton, QWidget)
from .backend_api import BackendAPI, DEFAULT_DB_PATH
from .records_table import RecordsWidget
from .layout_editor import LayoutEditor
from .preview import PreviewWidget
from .main_view import (PreviewPanel, PrintQueueDialog, PositionDialog, SettingsDialog, make_icon,
                        camera_available, CameraDialog)
from .dialogs import ImportDialog, ExportDialog, confirm_missing_photos, run_snapshot_job, describe_result, show_result_warnings
from .backend_api import print_snapshot


# Хуки для тестов: clear_marks_hook(parent, n) -> bool; position_hook(dialog) -> dict|None; about_hook(text)
clear_marks_hook = None
position_hook = None
about_hook = None

MENUS = ["Файл", "Дизайн", "Рисование", "Редактировать", "Просмотр", "Опции", "База данных", "Помощь"]
STYLE = """
QMainWindow { background:#F7FAFC; }
QToolBar { background:#FFFFFF; border-bottom:1px solid #E2E8F0; spacing:2px; padding:2px; }
QToolBar QToolButton { padding:3px 6px; border-radius:5px; color:#2D3748; }
QToolBar QToolButton:hover { background:#EBF4FF; }
QToolBar QToolButton:checked { background:#BEE3F8; }
QTableView { gridline-color:#E2E8F0; selection-background-color:#3182CE; alternate-background-color:#F7FAFC; }
QHeaderView::section { background:#EDF2F7; padding:4px; border:0; border-right:1px solid #E2E8F0; font-weight:600; }
QTabWidget::pane { border:1px solid #E2E8F0; border-radius:4px; }
"""


class MainWindow(QMainWindow):
    STATE_VERSION = 2

    def __init__(self, api: BackendAPI | None = None):
        super().__init__()
        self.setObjectName("bg_main_window")
        self.setStyleSheet(STYLE)
        self.settings = QSettings("BadgeGenerator", "Frontend")
        self._own_api = api is None
        self.api = api or BackendAPI(self.settings.value("db_path", str(DEFAULT_DB_PATH)))
        self.resize(1440, 880)
        self.side = "front"

        # --- главный вид: таблица (≈65%) | Предпросмотр / Поля ---
        self.records = RecordsWidget(self.api)
        self.preview_panel = PreviewPanel(self.api)
        self.splitter = QSplitter(Qt.Orientation.Horizontal); self.splitter.setObjectName("main_splitter")
        self.splitter.addWidget(self.records); self.splitter.addWidget(self.preview_panel)
        self.splitter.setStretchFactor(0, 65); self.splitter.setStretchFactor(1, 35); self.splitter.setSizes([930, 500])
        # отдельный режим — редактор макета (панель свойств внутри) и подробный предпросмотр
        self.layout_editor = LayoutEditor(self.api)
        self.preview = PreviewWidget(self.api)
        self.tabs = QTabWidget(); self.tabs.setDocumentMode(True)
        self.tabs.addTab(self.splitter, "Главная"); self.tabs.addTab(self.layout_editor, "Редактор макета")
        self.tabs.addTab(self.preview, "Предпросмотр")
        self.tabs.currentChanged.connect(self._tab_changed)
        self.setCentralWidget(self.tabs)
        self.layout_editor.status.connect(self._editor_changed)
        self.records.view.selectionModel().selectionChanged.connect(lambda *_: self._on_record_selected())
        self.records.model.modelReset.connect(self._on_record_selected)
        self.preview_panel.layout_fields.itemClicked.connect(self._layout_field_clicked)

        self._build_actions(); self._build_menus(); self._build_toolbar()
        self._default_state = self.saveState(self.STATE_VERSION)
        self.restore_layout()
        self._update_title(); self._on_record_selected()

    # --- действия ---
    def _act(self, text, slot, icon=None, name=None, shortcut=None, checkable=False):
        a = QAction(text, self)
        if icon: a.setIcon(make_icon(icon))
        if shortcut: a.setShortcut(shortcut)
        a.setCheckable(checkable); a.triggered.connect(slot)
        a.setObjectName(name or ("act_" + (icon or text))); return a

    def _build_actions(self):
        A = self._act; le = self.layout_editor
        self.act_connect = A("Подключить БД", self.open_db, "connect", "act_connect", "Ctrl+O")
        self.act_disconnect = A("Отключить БД", self.disconnect_db, "disconnect", "act_disconnect")
        self.act_settings = A("Настройка", self.open_settings, "settings", "act_settings")
        self.act_save = A("Сохранить", self.save_all, "save", "act_save", "Ctrl+S")
        self.act_print = A("Печать", self.do_print, "print", "act_print", "Ctrl+P")
        self.act_queue = A("Очередь печати", self.show_print_queue, "queue", "act_queue")
        self.act_printed = A("Напечатано / Не напечатано", self.toggle_printed_filter, "printed", "act_printed_filter")
        self.act_front = A("Лицевая", lambda: self.set_side("front"), "front", "act_front", checkable=True)
        self.act_back = A("Оборот", lambda: self.set_side("back"), "back", "act_back", checkable=True)
        g = QActionGroup(self); g.addAction(self.act_front); g.addAction(self.act_back); self.act_front.setChecked(True)
        self.act_text = A("Текст", lambda: le.run_tool("text"), "text", "act_text")
        self.act_position = A("Положение", self.edit_position, "position", "act_position")
        self.act_add = A("Добавить элемент", self._add_menu_popup, "add", "act_add_element")
        self.act_remove = A("Удалить элемент", le.delete_element, "remove", "act_remove_element")
        self.act_capture = A("Захват изображения", self.capture_image, "capture", "act_capture")
        self.act_import = A("Импорт…", self.do_import, None, "act_import", "Ctrl+I")
        self.act_export = A("Экспорт…", self.do_export, None, "act_export", "Ctrl+E")
        self.act_exit = A("Выход", self.close, None, "act_exit")
        self.act_editor = A("Редактор макета", self.show_editor, "design", "act_editor")
        self.act_main = A("Главный вид", self.show_main, None, "act_main")
        self.act_full_preview = A("Подробный предпросмотр", lambda: self.tabs.setCurrentWidget(self.preview), None, "act_full_preview")
        self.act_zoom_in = A("Увеличить", lambda: le.zoom(1.25), None, "act_zoom_in", "Ctrl++")
        self.act_zoom_out = A("Уменьшить", lambda: le.zoom(0.8), None, "act_zoom_out", "Ctrl+-")
        self.act_zoom_fit = A("По размеру окна", lambda: le.zoom(None), None, "act_zoom_fit")
        self.act_grid = A("Сетка", lambda on: le.set_grid(on, int(self.settings.value("editor/grid", 20))), None, "act_grid", checkable=True)
        self.act_reset_layout = A("Вернуть расположение панелей", self.reset_layout, None, "act_reset_layout")
        self.act_rec_add = A("Добавить запись", self.records.add, None, "act_rec_add")
        self.act_rec_edit = A("Изменить запись", self.records.edit, None, "act_rec_edit")
        self.act_rec_del = A("Удалить запись", self.records.delete, None, "act_rec_del")
        self.act_mark_all = A("Отметить все для печати", lambda: self.records._mark_all(True), None, "act_mark_all")
        self.act_unmark_all = A("Снять отметки печати", lambda: self.records._mark_all(False), None, "act_unmark_all")
        self.act_about = A("О программе", self.about, None, "act_about")
        self.add_menu = QMenu("Добавить элемент", self)
        for a in le.tool_actions.values(): self.add_menu.addAction(a)
        self.act_add.setMenu(self.add_menu)

    def _build_menus(self):
        le = self.layout_editor; mb = self.menuBar(); self.menus = {}
        groups = {
            "Файл": [self.act_save, None, self.act_print, self.act_queue, None, self.act_exit],
            "Дизайн": [self.act_editor, self.act_main, None, self.act_front, self.act_back, le.tool_actions["background"]],
            "Рисование": [a for k, a in le.tool_actions.items() if k != "background"],
            "Редактировать": [self.act_remove, le.act_up, le.act_down, self.act_position, None,
                              self.act_rec_add, self.act_rec_edit, self.act_rec_del, self.act_capture],
            "Просмотр": [self.act_main, self.act_editor, self.act_full_preview, None, self.act_zoom_in, self.act_zoom_out,
                         self.act_zoom_fit, self.act_grid, None, self.act_reset_layout],
            "Опции": [self.act_settings],
            "База данных": [self.act_connect, self.act_disconnect, None, self.act_import, self.act_export, None,
                            self.act_mark_all, self.act_unmark_all, self.act_printed],
            "Помощь": [self.act_about],
        }
        for name in MENUS:
            m = mb.addMenu(name); self.menus[name] = m
            for a in groups[name]:
                m.addSeparator() if a is None else m.addAction(a)

    def _build_toolbar(self):
        tb = self.addToolBar("Основная"); tb.setObjectName("tb_main"); self.toolbar = tb
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon); tb.setIconSize(tb.iconSize() * 0.9)
        for a in (self.act_connect, self.act_disconnect, self.act_settings, self.act_save, None, self.act_print,
                  self.act_queue, self.act_printed, None, self.act_front, self.act_back, None, self.act_text,
                  self.act_position, self.act_add, self.act_remove, None, self.act_capture):
            tb.addSeparator() if a is None else tb.addAction(a)
        b = tb.widgetForAction(self.act_add)
        if isinstance(b, QToolButton): b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.tb_elements = self.toolbar   # совместимость: инструменты элементов доступны через меню «Добавить элемент»

    def toolbar_texts(self):
        return [a.text() for a in self.toolbar.actions() if not a.isSeparator()]

    def _add_menu_popup(self):
        b = self.toolbar.widgetForAction(self.act_add)
        self.add_menu.popup(b.mapToGlobal(b.rect().bottomLeft()) if b else self.cursor().pos())

    # --- режимы ---
    def show_editor(self):
        self.tabs.setCurrentWidget(self.layout_editor)

    def show_main(self):
        self.tabs.setCurrentWidget(self.splitter)

    def set_side(self, side):
        self.side = side
        (self.act_front if side == "front" else self.act_back).setChecked(True)
        i = self.layout_editor.side_box.findData(side)
        if self.layout_editor.side_box.currentIndex() != i: self.layout_editor.side_box.setCurrentIndex(i)
        self.preview_panel.set_side(side)

    def _editor_changed(self, msg):
        self.statusBar().showMessage(msg)
        if self.layout_editor.side != self.side:
            self.side = self.layout_editor.side; (self.act_front if self.side == "front" else self.act_back).setChecked(True)
            self.preview_panel.side = self.side
        self.preview_panel.refresh()

    def _layout_field_clicked(self, item):
        eid = item.data(Qt.ItemDataRole.UserRole)
        if eid is not None: self.layout_editor.load(self.side, eid)

    # --- расположение (сплиттер + окно) ---
    def save_layout(self):
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/state", self.saveState(self.STATE_VERSION))
        self.settings.setValue("window/splitter", self.splitter.saveState())
        self.settings.sync()

    def restore_layout(self):
        g = self.settings.value("window/geometry"); st = self.settings.value("window/state")
        sp = self.settings.value("window/splitter")
        if g is not None: self.restoreGeometry(g)
        if sp is not None: self.splitter.restoreState(sp)
        if st is not None: return self.restoreState(st, self.STATE_VERSION)
        return sp is not None

    def reset_layout(self):
        self.restoreState(self._default_state, self.STATE_VERSION)
        total = sum(self.splitter.sizes()) or 1430
        self.splitter.setSizes([int(total * 0.65), total - int(total * 0.65)])
        self.toolbar.show()

    # --- выбор записи → предпросмотр/поля/холст ---
    def selected_person_id(self):
        ids = self.records.selected_ids()
        return ids[0] if ids else None

    def _on_record_selected(self):
        pid = self.selected_person_id()
        self.preview_panel.set_person(pid)
        self.layout_editor.set_person(pid)
        i = self.preview.person_box.findData(pid)
        if pid is not None and i >= 0: self.preview.person_box.setCurrentIndex(i)

    # --- команды панели инструментов ---
    def disconnect_db(self):
        self.switch_db(":memory:")
        self.statusBar().showMessage("БД отключена: открыта временная база в памяти")

    def open_settings(self, values=None):
        d = SettingsDialog(self.api, self.settings, self)
        if values is not None:
            if "base_dir" in values: d.base_dir.setText(values["base_dir"])
            if "grid" in values: d.grid.setValue(values["grid"])
            res = d.apply()
        elif d.exec():
            res = d.apply()
        else:
            return None
        self.refresh_all(); return res

    def save_all(self):
        self.save_layout()
        self.statusBar().showMessage("Сохранено: записи и макет пишутся в БД сразу; расположение окна сохранено")
        return True

    def show_print_queue(self, exec_=True):
        d = PrintQueueDialog(self.api, self, on_print=self.do_print)
        if exec_: d.exec(); self.records.reload()
        return d

    def toggle_printed_filter(self):
        t = self.records.cycle_printed_filter()
        self.act_printed.setToolTip(f"Фильтр по печати: {t}"); self.statusBar().showMessage(f"Фильтр по печати: {t}")
        return t

    def edit_position(self):
        le = self.layout_editor
        if not le.current:
            self.statusBar().showMessage("Выберите элемент макета (вкладка «Поля макета» или редактор)"); return None
        d = PositionDialog({**le.current.el, **le.current.geometry()}, self)
        val = position_hook(d) if position_hook is not None else (d.value() if d.exec() else None)
        if val:
            eid = le.current.el["id"]; self.api.update_element(eid, **val); le.load(le.side, eid)
        return val

    def capture_image(self, path=None):
        pid = self.selected_person_id()
        if pid is None:
            self.statusBar().showMessage("Выберите запись для захвата фото"); return None
        if path is None:
            if camera_available():
                os.makedirs(os.path.join(self.api.base_dir, "photos"), exist_ok=True)
                d = CameraDialog(os.path.join(self.api.base_dir, "photos", f"capture_{pid}.png"), self)
                path = d.path if d.exec() else None
            else:
                path, _ = QFileDialog.getOpenFileName(self, "Фото записи", self.api.base_dir,
                                                      "Изображения (*.png *.jpg *.jpeg *.bmp)")
            if not path: return None
        try:
            rel = os.path.relpath(path, self.api.base_dir); path = path if rel.startswith("..") else rel
        except ValueError:
            pass
        self.api.update_person(pid, photo_path=path)
        self.records.reload(); self._select_person(pid)
        self.statusBar().showMessage(f"Фото записи #{pid}: {path}")
        return path

    def _select_person(self, pid):
        r = self.records.model.row_of(pid)
        if r >= 0:
            self.records.view.selectRow(self.records.proxy.mapFromSource(self.records.model.index(r, 1)).row())

    def about(self):
        text = ("Генератор пропусков\nРедактор шаблонов карт CR80, база записей, печать и экспорт.\n"
                f"Схема БД: v{self.api.schema_version()}")
        if about_hook is not None: about_hook(text)
        else: QMessageBox.about(self, "О программе", text)
        return text

    def _update_title(self):
        self.setWindowTitle(f"Генератор пропусков — {self.api.db_path}")
        self.statusBar().showMessage(f"БД: {self.api.db_path}; база путей фото: {self.api.base_dir}")

    def refresh_all(self):
        self.records.reload(); self.layout_editor.reload(); self.preview.refresh(); self._on_record_selected()

    def _tab_changed(self, i):
        w = self.tabs.widget(i)
        if w is self.splitter: self.preview_panel.refresh()
        if w is self.preview: self.preview.refresh()
        elif w is self.layout_editor: self.layout_editor.reload()

    def open_db(self):
        p, _ = QFileDialog.getSaveFileName(self, "Открыть или создать БД", str(self.api.db_path),
                                           "SQLite (*.db *.sqlite)", options=QFileDialog.Option.DontConfirmOverwrite)
        if p: self.switch_db(p)

    def switch_db(self, path):
        self.api.open_db(path)
        if str(path) != ":memory:": self.settings.setValue("db_path", str(path))
        self.refresh_all(); self._update_title()

    def do_import(self):
        ImportDialog(self.api, self).exec(); self.refresh_all()

    def do_export(self):
        ExportDialog(self.api, self.records.selected_ids(), self).exec()

    def do_print(self, _=False, printer=None, sides=("front", "back")):
        """QPrintDialog → предпроверка фото → snapshot (GUI) → print_snapshot в рабочем потоке.
        Печатаются только записи с print_mark=1. Возвращает (result, error)."""
        from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
        ids = [p["id"] for p in self.api.list_persons(only_marked=True)]
        if not ids:
            QMessageBox.information(self, "Печать", "Нет записей, отмеченных для печати."); return None, None
        if printer is None:
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            if QPrintDialog(printer, self).exec() != QPrintDialog.DialogCode.Accepted: return None, None
            choice, ok = QInputDialog.getItem(self, "Печать", "Стороны:", ["Обе", "Лицевая", "Оборотная"], 0, False)
            if not ok: return None, None
            sides = {"Обе": ("front", "back"), "Лицевая": ("front",), "Оборотная": ("back",)}[choice]
        go, allow = confirm_missing_photos(self, self.api, ids)
        if not go:
            self.statusBar().showMessage("Печать отменена: есть записи без фото"); return None, None
        snap = self.api.snapshot(ids, sides)
        res, err = run_snapshot_job(self, "Печать", print_snapshot, snap, printer, self.api.base_dir,
                                    allow_missing_photo=allow)
        msg = describe_result(res, err, "Печать")
        self.statusBar().showMessage(msg)
        if err is not None: QMessageBox.warning(self, "Печать", msg)
        elif res is not None and not getattr(res, "cancelled", False) and int(res) > 0:
            printed = list(dict.fromkeys(item["person"]["id"] for item in snap))   # реально напечатанные
            self._offer_clear_marks(printed)
        if err is None: show_result_warnings(self, res, "Печать")
        return res, err

    def _offer_clear_marks(self, ids):
        """D5: после успешной печати предложить снять отметки только с напечатанных записей."""
        n = len(ids)
        q = f"Печать прошла успешно? Снять отметки с {n} записей?"
        if clear_marks_hook is not None:
            yes = bool(clear_marks_hook(self, n))
        else:
            yes = QMessageBox.question(self, "Печать", q, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                       QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes
        if not yes:
            return 0
        changed = self.api.mark_printed(ids)   # print_mark=0 + printed_at=now (атомарно, Backend)
        self.records.reload()
        self.statusBar().showMessage(f"Отметки сняты: {changed}")
        return changed

    def closeEvent(self, ev):
        self.save_layout()
        if self._own_api: self.api.close()
        super().closeEvent(ev)
