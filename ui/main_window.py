"""Главное окно этапа 12: лента (ribbon) вместо меню и панели инструментов.
Каждое действие — ровно один QAction и одно место в ленте; горячие клавиши и контекстные меню
используют те же QAction. Вкладка ленты «База данных» показывает таблицу записей, остальные — редактор."""
import os
from pathlib import Path
from PyQt6.QtCore import QSettings, Qt, QTimer, QThreadPool
from PyQt6.QtGui import QAction, QActionGroup, QKeySequence
from PyQt6.QtWidgets import (QMainWindow, QFileDialog, QMessageBox, QInputDialog, QSplitter, QMenu, QStackedWidget,
                             QWidget, QVBoxLayout, QWidgetAction, QSpinBox, QLabel, QHBoxLayout, QColorDialog, QComboBox)
from .backend_api import (BackendAPI, DEFAULT_DB_PATH, TYPE_NAMES,
                          RecoverableProjectError, ProjectLockedError, ProjectSaveError,
                          UnsavedChangesError, TemplateEditActiveError, recover)
from .records_table import RecordsWidget, PRINTED_FILTERS
from .layout_editor import LayoutEditor
from .object_properties import ObjectPropertiesDock
from .main_view import (PreviewPanel, PrintQueueDialog, PositionDialog, SettingsDialog, FieldManager, ALIGN,
                        aligned_geometry)
from .ribbon import Ribbon, glyph
from . import stage15
from .dialogs import ImportDialog, ExportDialog, confirm_missing_photos, run_print_job, describe_result, show_result_warnings
from .backend_api import print_snapshot, setup_printer


# Хуки для тестов: clear_marks_hook(parent, n) -> bool; position_hook(dialog) -> dict|None; about_hook(text);
# ask_hook(kind, parent) -> значение вместо модального вопроса (find/goto/save_as/compact/restore/color/help)
clear_marks_hook = None
position_hook = None
about_hook = None
ask_hook = None

STYLE = """
QMainWindow { background:#F6F8F7; }
QTabWidget#ribbon::pane { border:0; border-bottom:1px solid #D5DCDA; background:#FFFFFF; }
QTabWidget#ribbon QTabBar::tab { padding:4px 12px; }
QTabWidget#ribbon QTabBar::tab:selected { color:#2E7D6B; font-weight:600; }
QToolButton { border-radius:4px; padding:2px; color:#24302D; }
QToolButton:hover { background:#E3F1EC; }
QToolButton:checked { background:#C8E4DA; }
QTableView { gridline-color:#E2E8F0; selection-background-color:#2E7D6B; }
QHeaderView::section { background:#EEF2F1; padding:4px; border:0; border-right:1px solid #DDE3E1; font-weight:600; }
"""
HELP_TEXT = ("Лента: «Файл» — проект и данные; «Главная» — буфер и сторона; «Рисование» — объекты и стиль;\n"
             "«Редактировать» — история, объект, порядок; «Просмотр» — масштаб и сетка; «База данных» — записи,\n"
             "фильтр, печать и метки. Правый клик по холсту или таблице — те же команды. "
             "Alt+клик по холсту выбирает следующий объект под курсором.")


class StrokeWidthAction(QWidgetAction):
    """«Толщина границы»: виджет создаётся заново для каждого контейнера (группа ленты и меню свёрнутой группы)."""

    def __init__(self, parent, on_change):
        super().__init__(parent); self.setObjectName("act_style_stroke_w"); self.setText("Толщина границы")
        self.on_change, self.value, self.spins = on_change, 0, []

    def createWidget(self, parent):
        w = QWidget(parent); h = QVBoxLayout(w); h.setContentsMargins(2, 4, 2, 0); h.setSpacing(1)
        sp = QSpinBox(); sp.setRange(0, 50); sp.setSuffix(" px"); sp.setToolTip("Толщина границы"); sp.setValue(self.value)
        sp.editingFinished.connect(lambda sp=sp: self._changed(sp.value()))
        h.addWidget(QLabel("Толщина")); h.addWidget(sp); h.addStretch(1)
        self.spins.append(sp); w.destroyed.connect(lambda *_ , sp=sp: self.spins.remove(sp) if sp in self.spins else None)
        return w

    def _changed(self, v):
        if v == self.value: return
        self.set_value(v); self.on_change(v)

    def set_value(self, v):
        self.value = v
        for sp in self.spins:
            sp.blockSignals(True); sp.setValue(v); sp.blockSignals(False)

    @property
    def spin(self): return self.spins[0]


class FieldWidgetAction(QWidgetAction):
    """Этап 15: поле ленты «Редактировать» (шрифт / размер / отступы): подпись + виджет, создаётся для каждого контейнера."""

    def __init__(self, parent, name, text, factory, on_change, tip=None):
        super().__init__(parent); self.setObjectName(name); self.setText(text)
        self.factory, self.on_change, self.tip, self.widgets = factory, on_change, tip, []

    def createWidget(self, parent):
        w = QWidget(parent); h = QVBoxLayout(w); h.setContentsMargins(2, 4, 2, 0); h.setSpacing(1)
        e = self.factory(); e.setToolTip(self.tip or self.text()); self.on_change(e)
        h.addWidget(QLabel(self.text())); h.addWidget(e); h.addStretch(1)
        self.widgets.append(e); w.destroyed.connect(lambda *_, e=e: self.widgets.remove(e) if e in self.widgets else None)
        return w

    @property
    def widget(self): return self.widgets[0]


class MainWindow(QMainWindow):
    STATE_VERSION = 3
    MIN_W = 1000

    def __init__(self, api: BackendAPI | None = None):
        super().__init__()
        self.setObjectName("bg_main_window"); self.setStyleSheet(STYLE)
        self.settings = QSettings("BadgeGenerator", "Frontend")
        self._own_api = api is None
        self.api = api if api is not None else self._open_api(self.settings.value("db_path", str(DEFAULT_DB_PATH)))
        self._dirty_override = None   # тесты: set_project_dirty принудительно показывает «*» / снимает
        self.side, self.clipboard = "front", None
        self.resize(1440, 880)

        self.layout_editor = le = LayoutEditor(self.api)
        self.records = RecordsWidget(self.api)
        self.preview_panel = PreviewPanel(self.api)
        self.splitter = QSplitter(Qt.Orientation.Horizontal); self.splitter.setObjectName("main_splitter")
        self.splitter.addWidget(self.records); self.splitter.addWidget(self.preview_panel)
        self.splitter.setStretchFactor(0, 65); self.splitter.setStretchFactor(1, 35); self.splitter.setSizes([900, 480])
        self.db_page = QWidget(); dl = QVBoxLayout(self.db_page); dl.setContentsMargins(4, 4, 4, 0)
        dl.addWidget(self.records.filter); dl.addWidget(self.splitter, 1)
        self.stack = QStackedWidget(); self.stack.addWidget(le); self.stack.addWidget(self.db_page)

        self.ribbon = Ribbon()
        # Лента на всю ширину окна выше области доков: панель свойств
        # начинается под лентой, а не рядом с ней до верха окна.
        self.setMenuWidget(self.ribbon)
        self.setCentralWidget(self.stack)
        self.props_dock = ObjectPropertiesDock(le, self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.props_dock)
        le.object_props = self.props_dock.panel
        self.pos_label = QLabel("X: —  Y: — мм"); self.statusBar().addPermanentWidget(self.pos_label)

        self._build_actions(); self._build_ribbon(); self._build_context_menus()
        self.ribbon.currentChanged.connect(self._ribbon_changed)
        le.status.connect(self._editor_changed)
        le.cursor_moved.connect(lambda x, y: self.pos_label.setText(f"X: {x:.1f}  Y: {y:.1f} мм"))
        le.scene.selectionChanged.connect(self._sync_selection)
        self._sel_timer = QTimer(self, singleShot=True, interval=0, timeout=self._apply_record_selection)
        self._suspend_sel = False
        self.records.view.selectionModel().selectionChanged.connect(lambda *_: self._on_record_selected())
        self.records.model.modelReset.connect(self._on_record_selected)
        self.records.model.queue_toggle_requested.connect(self._checkbox_queue)
        self.setMinimumWidth(self.MIN_W)
        self._default_state = self.saveState(self.STATE_VERSION)
        self.restore_layout()
        self.ribbon.select("Главная"); self._ribbon_changed(self.ribbon.currentIndex())
        self._update_title(); self._on_record_selected(); self._sync_selection()
        self.sync_template_style(); self.offer_template_restore()

    # --- действия ---
    def _act(self, name, text, slot, icon=None, shortcut=None, checkable=False, icon_text=None, tip=None):
        a = QAction(text, self); a.setObjectName(name)
        if icon: a.setIcon(glyph(icon))
        if icon_text: a.setIconText(icon_text)
        if shortcut:
            a.setShortcuts([QKeySequence(s) for s in (shortcut if isinstance(shortcut, (list, tuple)) else [shortcut])])
            a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        a.setToolTip(tip or (text + (f" ({a.shortcut().toString()})" if shortcut else "")))
        a.setCheckable(checkable)
        if slot is not None:
            # D20/D21: triggered(bool) НЕ передаётся в слот — иначе checked=False попадал в values/exec_ и т.п.
            if checkable: a.triggered.connect(lambda checked, f=slot: f(checked))
            else: a.triggered.connect(lambda _checked=False, f=slot: f())
        self.addAction(a); return a

    def _build_actions(self):
        A, le = self._act, self.layout_editor
        # Файл
        self.act_new = A("act_new", "Новый проект", self.new_project, "new", "Ctrl+N", icon_text="Новый\nпроект")
        self.act_open = A("act_open", "Открыть проект…", self.open_db, "open", "Ctrl+O", icon_text="Открыть")
        # этап 15 F3: один QAction «Сохранить» (Ctrl+S) на вкладке «Файл»; в режиме шаблона черновик не фиксирует.
        self.act_project_save = A("act_project_save", "Сохранить", self.save_project, "save", "Ctrl+S",
                                  icon_text="Сохранить", tip="Сохранить проект (Ctrl+S)")
        self.act_save_as = A("act_save_as", "Сохранить как…", self.save_as, "save", "Ctrl+Shift+S", icon_text="Сохранить\nкак…")
        self.act_import = A("act_import", "Импорт записей…", self.do_import, "import", "Ctrl+I", icon_text="Импорт")
        self.act_export = A("act_export", "Экспорт…", self.do_export, "export", "Ctrl+E", icon_text="Экспорт")
        self.act_settings = A("act_settings", "Настройки…", self.open_settings, "settings", "Ctrl+,", icon_text="Настройки")
        self.act_exit = A("act_exit", "Выход", self.close, "exit", "Ctrl+Q")
        # Главная
        self.act_cut = A("act_cut", "Вырезать", self.cut, "cut", "Ctrl+X")
        self.act_copy = A("act_copy", "Копировать", self.copy, "copy", "Ctrl+C")
        self.act_paste = A("act_paste", "Вставить", self.paste, "paste", "Ctrl+V")
        self.act_duplicate = A("act_duplicate", "Дублировать", self.duplicate, "duplicate", "Ctrl+D")
        self.act_side = A("act_side", "Сторона: лицевая", lambda on: self.set_side("back" if on else "front"), "front",
                          "Ctrl+Tab", checkable=True, icon_text="Лицевая")
        self.act_background = A("act_background", "Фон стороны…", lambda: le.run_tool("background"), "background", icon_text="Фон")
        # Рисование
        self.tool_actions = {}
        keys = {"field": "F", "photo": "P", "barcode": "B", "qr": "Q", "text": "T", "rect": "R", "ellipse": "E",
                "line": "L", "image": "I"}
        icons = {"field": "text", "rect": "rect"}
        for t, k in keys.items():
            self.tool_actions[t] = A(f"act_tool_{t}", TYPE_NAMES[t], lambda _=False, t=t: le.run_tool(t), icons.get(t, t), k)
        self.act_style_fill = A("act_style_fill", "Цвет заливки…", lambda: self.pick_color("fill"), "fill", icon_text="Заливка")
        self.act_style_stroke = A("act_style_stroke", "Цвет границы…", lambda: self.pick_color("stroke"), "stroke", icon_text="Граница")
        self.act_style_stroke_w = StrokeWidthAction(self, lambda v: le.set_prop("stroke_width", v))
        self.act_align = A("act_align", "Выровнять", None, "align", icon_text="Выровнять")
        self.align_menu = QMenu("Выровнять", self); self.align_actions = {}
        for how, t in ALIGN:
            sub = QAction(t, self); sub.setObjectName(f"act_align_{how}"); sub.triggered.connect(lambda _=False, h=how: self.align(h))
            self.align_menu.addAction(sub); self.align_actions[how] = sub
        self.act_align.setMenu(self.align_menu)
        # Редактировать — этап 15: форматирование и шаблон в одну горизонтальную строку групп
        def _font():
            cb = QComboBox(); cb.setMaximumWidth(150); cb.setMinimumContentsLength(8); return cb
        def _spin(lo, hi, v, suf):
            def mk():
                sp = QSpinBox(); sp.setRange(lo, hi); sp.setValue(v); sp.setSuffix(suf); return sp
            return mk
        self.act_font = FieldWidgetAction(self, "act_font", "Шрифт", _font, self._bind_font, "Шрифт шаблона")
        def _bind_font_size(e):
            timer = QTimer(e, singleShot=True, interval=300)
            timer.timeout.connect(lambda e=e: le.current and le.set_props(font_size=e.value()))
            e.valueChanged.connect(lambda *_e, timer=timer: timer.start())
        self.act_font_size = FieldWidgetAction(self, "act_font_size", "Размер", _spin(4, 200, 14, " pt"),
            _bind_font_size)
        self.act_padding = FieldWidgetAction(self, "act_padding", "Отступы", _spin(0, 200, 0, " px"), self._bind_padding,
                                             "Отступы шаблона (0…200 px)")
        self.act_text_color = A("act_text_color", "Цвет текста…", lambda: self.pick_color("color"), "text", icon_text="Цвет\nтекста")
        fp = stage15.TemplateTools(self, le)
        self.act_template_mode = A("act_template_mode", "Режим шаблона", fp.set_template_mode, "edit_card", checkable=True,
                                   icon_text="Режим\nшаблона", tip="Режим создания шаблона: элементы расставляются вручную")
        self.act_template_save = A("act_template_save", "✓ Сохранить шаблон", fp.save_template, "printed", icon_text="✓ Сохранить\nшаблон")
        self.act_template_manager = A("act_template_manager", "Менеджер шаблонов…", fp.open_manager, "table", icon_text="Менеджер\nшаблонов")
        fp.bind(self.act_template_mode, self.act_template_save); self.template_tools = fp
        self.act_undo = A("act_undo", "Отменить", self.undo, "undo", "Ctrl+Z")
        self.act_redo = A("act_redo", "Повторить", self.redo, "redo", ["Ctrl+Y", "Ctrl+Shift+Z"])
        self.act_delete_element = A("act_delete_element", "Удалить объект", self.delete_element, "delete", "Del", icon_text="Удалить")
        self.act_position = A("act_position", "Положение…", self.edit_position, "position", "Ctrl+K", icon_text="Положение")
        self.act_z_up = A("act_z_up", "Выше", lambda: self._z(1), "z_up", "Ctrl+]")
        self.act_z_down = A("act_z_down", "Ниже", lambda: self._z(-1), "z_down", "Ctrl+[")
        # Просмотр
        self.act_zoom_in = A("act_zoom_in", "Увеличить", lambda: le.zoom(1.25), "zoom_in", ["Ctrl++", "Ctrl+="])
        self.act_zoom_out = A("act_zoom_out", "Уменьшить", lambda: le.zoom(0.8), "zoom_out", "Ctrl+-")
        self.act_zoom_fit = A("act_zoom_fit", "По размеру", lambda: le.zoom(None), "zoom_fit", "Ctrl+0")
        self.act_grid = A("act_grid", "Сетка", lambda on: le.set_grid(on, int(self.settings.value("editor/grid", 20))),
                          "grid", "Ctrl+'", checkable=True)
        self.act_rulers = A("act_rulers", "Линейки", le.set_rulers, "ruler", checkable=True); self.act_rulers.setChecked(True)
        self.act_show_render = A("act_show_render", "Рендер под рамками", le.set_show_render, "render", checkable=True,
                                 icon_text="Рендер")
        self.act_show_render.setChecked(le.show_render)
        self.act_reset_layout = A("act_reset_layout", "Сбросить расположение", self.reset_layout, "reset", icon_text="Сбросить\nокно")
        # База данных
        self.act_connect = A("act_connect", "Подключить БД…", self.connect_db, "connect", icon_text="Подключить")
        self.act_disconnect = A("act_disconnect", "Отключить БД", self.disconnect_db, "disconnect", icon_text="Отключить")
        self.act_field_manager = A("act_field_manager", "Менеджер полей…", self.field_manager, "table", icon_text="Настр.\nполя")
        self.act_compact = A("act_compact", "Сжать и восстановить", None, "db", icon_text="Сжать /\nвосст.")
        cm = QMenu(self)
        self.act_compact_run = cm.addAction("Сжать и создать бэкап…", self.compact)
        self.act_restore = cm.addAction("Восстановить из бэкапа…", self.restore)
        self.act_compact.setMenu(cm)
        self.act_print = A("act_print", "Печать…", self.do_print, "print", "Ctrl+P", icon_text="Печать")
        self.act_queue = A("act_queue", "Очередь печати", self.show_print_queue, "queue", icon_text="Очередь")
        self.act_queue_toggle = A("act_queue_toggle", "В очередь / из очереди", self.queue_toggle, "mark", "Space",
                                  icon_text="В очередь")
        self.act_mark_printed = A("act_mark_printed", "Напечатано", self.mark_printed, "printed")
        self.act_mark_unprinted = A("act_mark_unprinted", "Не напечатано", self.mark_unprinted, "unprinted", icon_text="Не напечат.")
        self.display_group = QActionGroup(self); self.display_actions = {}
        for v, t in PRINTED_FILTERS:
            key = {None: "all", True: "printed", False: "unprinted"}[v]
            a = A(f"act_display_{key}", t, lambda _=False, v=v: self.set_display(v), {"all": "table"}.get(key, key),
                  checkable=True, icon_text={"all": "Все", "printed": "Напечат.", "unprinted": "Ненапечат."}[key])
            self.display_group.addAction(a); self.display_actions[v] = a
        self.display_actions[None].setChecked(True)
        self.act_find = A("act_find", "Поиск по данным…", self.find, "zoom_in", "Ctrl+F", icon_text="Поиск")
        self.act_goto = A("act_goto", "Перейти к положению…", self.goto, "goto", "Ctrl+G", icon_text="Перейти")
        self.act_card_add = A("act_card_add", "Добавить карту", self.records.add, "add", "Ins", icon_text="Добавить")
        self.act_card_edit = A("act_card_edit", "Изменить карту", self.records.edit, "edit", "Return", icon_text="Изменить")
        self.act_card_delete = A("act_card_delete", "Удалить карту", self.records.delete, "delete", "Shift+Del", icon_text="Удалить")
        self.act_filter_apply = A("act_filter_apply", "Применить", self.apply_filter, None)
        self.records.filter.set_apply_action(self.act_filter_apply)
        # Помощь
        self.act_help = A("act_help", "Справка", self.help, "help", "F1")
        self.act_about = A("act_about", "О программе", self.about, "about", icon_text="О\nпрограмме")
        # Действия, зависящие от выделения/режима
        le.selection_actions = [self.act_cut, self.act_copy, self.act_duplicate, self.act_delete_element, self.act_position,
                                self.act_z_up, self.act_z_down, self.act_align, self.act_style_fill, self.act_style_stroke,
                                self.act_style_stroke_w]
        self.editor_actions = le.selection_actions + [self.act_paste, self.act_undo, self.act_redo] + list(self.tool_actions.values())
        self.db_actions = [self.act_queue_toggle, self.act_card_edit, self.act_card_delete, self.act_mark_printed,
                           self.act_mark_unprinted]

    def _build_ribbon(self):
        R, T = self.ribbon, self.tool_actions
        R.add_group("Файл", "Проект", [self.act_new, self.act_open, self.act_project_save, self.act_save_as])
        R.add_group("Файл", "Данные", [self.act_import, self.act_export])
        R.add_group("Файл", "Параметры", [self.act_settings, self.act_exit])
        R.add_group("Главная", "Буфер", [self.act_cut, self.act_copy, self.act_paste, self.act_duplicate])
        R.add_group("Главная", "Сторона", [self.act_side, self.act_background])
        R.add_group("Рисование", "Данные", [T["field"], T["photo"], T["barcode"], T["qr"]])
        R.add_group("Рисование", "Фигуры", [T["text"], T["rect"], T["ellipse"], T["line"], T["image"]])
        R.add_group("Рисование", "Расположение", [self.act_align])
        R.add_group("Редактировать", "Шрифт", [self.act_font, self.act_font_size])
        R.add_group("Редактировать", "Отступы", [self.act_padding])
        R.add_group("Редактировать", "Цвет", [[self.act_text_color, self.act_style_fill]])
        R.add_group("Редактировать", "Граница", [self.act_style_stroke, self.act_style_stroke_w])
        R.add_group("Редактировать", "Шаблон", [[self.act_template_mode, self.act_template_save, self.act_template_manager]])
        R.add_group("Редактировать", "История", [[self.act_undo, self.act_redo]])
        R.add_group("Редактировать", "Объект", [[self.act_delete_element, self.act_position], [self.act_z_up, self.act_z_down]])  # порядок слоёв — в группе «Объект» (вписывается в 1024 px)
        R.add_group("Просмотр", "Масштаб", [self.act_zoom_in, self.act_zoom_out, self.act_zoom_fit])
        R.add_group("Просмотр", "Показать", [self.act_grid, self.act_rulers, self.act_show_render])
        R.add_group("Просмотр", "Окно", [self.act_reset_layout])
        R.add_group("База данных", "Подключение", [[self.act_connect, self.act_disconnect]])
        R.add_group("База данных", "Установки", [self.act_field_manager, self.act_compact])
        R.add_group("База данных", "Печать", [self.act_print, self.act_queue, self.act_queue_toggle])
        R.add_group("База данных", "Метка", [[self.act_mark_printed, self.act_mark_unprinted]])
        R.add_group("База данных", "Дисплей", [list(self.display_actions.values())])   # §4 п.3: столбик маленьких кнопок
        R.add_group("База данных", "Поиск", [self.act_find, self.act_goto])
        R.add_group("База данных", "Карта", [self.act_card_add, self.act_card_edit, self.act_card_delete])
        R.add_group("Помощь", "Справка", [self.act_help, self.act_about])
        # act_filter_apply — единственное место: кнопка блока фильтра под лентой (вкладка «База данных»)
        R.places[self.act_filter_apply] = ("База данных", "Блок фильтра")

    def _build_context_menus(self):
        le = self.layout_editor
        # клавиши, конфликтующие с вводом текста, действуют только в своём виджете (тот же QAction)
        for a, w in ((self.act_queue_toggle, self.records.view), (self.act_card_edit, self.records.view),
                     (self.act_card_delete, self.records.view), (self.act_delete_element, le.view)):
            self.removeAction(a); w.addAction(a); a.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.canvas_menu_actions = [self.act_cut, self.act_copy, self.act_paste, self.act_duplicate, None,
                                    self.act_delete_element, self.act_position, self.act_align, self.act_z_up, self.act_z_down,
                                    None, self.act_background]
        self.table_menu_actions = [self.act_card_add, self.act_card_edit, self.act_card_delete, None, self.act_queue_toggle,
                                   self.act_mark_printed, self.act_mark_unprinted, None, self.act_print]
        for w, acts in ((le.view, self.canvas_menu_actions),
                        (self.records.view, self.table_menu_actions)):
            w.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            w.customContextMenuRequested.connect(lambda pos, w=w, acts=acts: self._popup(w, acts, pos))

    def context_menu(self, acts):
        m = QMenu(self)
        for a in acts: m.addSeparator() if a is None else m.addAction(a)
        return m

    def _popup(self, w, acts, pos):
        self.context_menu(acts).popup(w.mapToGlobal(pos))

    def all_actions(self):
        """Все действия ленты (каждое — одно место)."""
        return list(self.ribbon.places)

    # --- режимы ---
    def _ribbon_changed(self, i):
        db = self.ribbon.tabText(i) == "База данных"
        self.stack.setCurrentWidget(self.db_page if db else self.layout_editor)
        if db: self.preview_panel.refresh()
        else: self.layout_editor.reload()
        if hasattr(self, "props_dock"):
            self.props_dock.setVisible(not db)
        self._sync_selection()

    def show_main(self):
        self.ribbon.select("База данных")

    def show_editor(self):
        if self.ribbon.tabText(self.ribbon.currentIndex()) == "База данных": self.ribbon.select("Главная")

    def set_side(self, side):
        self.side = side
        self.act_side.blockSignals(True); self.act_side.setChecked(side == "back"); self.act_side.blockSignals(False)
        t = "Оборот" if side == "back" else "Лицевая"
        self.act_side.setText(f"Сторона: {t.lower()}"); self.act_side.setIconText(t); self.act_side.setIcon(glyph(side))
        self.layout_editor.set_side(side); self.preview_panel.set_side(side)

    def _editor_changed(self, msg):
        self.statusBar().showMessage(msg)
        if self.layout_editor.side != self.side: self.set_side(self.layout_editor.side)
        self._sync_selection()

    def _sync_selection(self):
        sel = self.layout_editor.current is not None
        for a in self.layout_editor.selection_actions: a.setEnabled(sel)
        self.act_paste.setEnabled(self.clipboard is not None)
        self.act_undo.setEnabled(self.api.can_undo()); self.act_redo.setEnabled(self.api.can_redo())
        if sel:
            st = self.layout_editor.current.el.get("style") or {}
            self.act_style_stroke_w.set_value(int(st.get("stroke_width") or 0))
        has_rec = bool(self.records.selected_ids())
        for a in (self.act_queue_toggle, self.act_card_edit, self.act_card_delete, self.act_mark_printed, self.act_mark_unprinted):
            a.setEnabled(has_rec)

    # --- буфер ---
    _COPY_KEYS = ("type", "x", "y", "w", "h", "field_name", "static_value", "style", "side", "z_order")

    def copy(self):
        c = self.layout_editor.current
        if not c: return None
        self.clipboard = {k: c.el.get(k) for k in self._COPY_KEYS}; self._sync_selection(); return self.clipboard

    def cut(self):
        if self.copy() is None: return None
        self.delete_element(); return self.clipboard

    def paste(self, offset=20):
        if not self.clipboard: return None
        le = self.layout_editor
        kw = dict(self.clipboard); kw["x"] += offset; kw["y"] += offset; kw["side"] = le.side
        kw["z_order"] = max([i.el.get("z_order") or 0 for i in le.items()] + [0]) + 1
        eid = self.api.create_element(**kw); le.load(le.side, eid); self._sync_selection(); return eid

    def duplicate(self):
        saved = self.clipboard
        if self.copy() is None: return None
        eid = self.paste(); self.clipboard = saved; self._sync_selection(); return eid

    # --- стиль/объект ---
    def pick_color(self, key, color=None):
        le = self.layout_editor
        if not le.current: return None
        if color is None:
            if ask_hook is not None: color = ask_hook("color", self)
            else:
                st = le.current.el.get("style") or {}
                from PyQt6.QtGui import QColor
                c = QColorDialog.getColor(QColor(st.get(key) or "#000000"), self, "Цвет")
                color = c.name() if c.isValid() else None
        if not color: return None
        le.set_prop(key, color); self._sync_selection(); return color

    def align(self, how):
        le = self.layout_editor
        if not le.current: return None
        g = aligned_geometry({**le.current.el, **le.current.geometry()}, how)
        le.set_props(x=g["x"], y=g["y"]); return g

    def _z(self, d):
        self.layout_editor.move_z(d); self._sync_selection()

    def delete_element(self):
        self.layout_editor.delete_element(); self._sync_selection()

    def undo(self):
        r = self.api.undo(); self.layout_editor.reload(); self._sync_selection(); return r

    def redo(self):
        r = self.api.redo(); self.layout_editor.reload(); self._sync_selection(); return r

    def edit_position(self):
        """Одно место для X/Y/W/H — панель «Свойства объекта» (диалог PositionDialog больше не открывается)."""
        le = self.layout_editor
        if not le.current:
            self.statusBar().showMessage("Выберите объект на холсте"); return None
        if hasattr(self, "props_dock"):
            self.props_dock.show(); self.props_dock.raise_()
            self.props_dock.panel.expand_all()
        return None

    # --- расположение ---
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
        total = sum(self.splitter.sizes()) or 1380
        self.splitter.setSizes([int(total * 0.65), total - int(total * 0.65)])

    # --- записи ---
    def selected_person_id(self):
        ids = self.records.selected_ids()
        return ids[0] if ids else None

    def _on_record_selected(self):
        if self._suspend_sel:
            return
        self._sel_timer.start()

    def _apply_record_selection(self):
        pid = self.selected_person_id()
        db = self.stack.currentWidget() is self.db_page
        if db:
            self.preview_panel.set_person(pid)
            self.layout_editor._set_person_meta(pid)
        else:
            self.layout_editor.set_person(pid)
            self.preview_panel.person_id = pid
        self._sync_selection()

    def _select_person(self, pid):
        r = self.records.model.row_of(pid)
        if r >= 0:
            self.records.view.selectRow(self.records.proxy.mapFromSource(self.records.model.index(r, 1)).row())
        return r >= 0

    def apply_filter(self):
        ids = self.records.apply_filter()
        self.statusBar().showMessage("Фильтр сброшен" if ids is None else f"Фильтр: найдено {len(ids)}"); return ids

    def set_display(self, value):
        self.display_actions[value].setChecked(True)
        t = self.records.set_printed_filter(value); self.statusBar().showMessage(f"Дисплей: {t}"); return t

    def find(self, text=None):
        if text is None:
            if ask_hook is not None: text = ask_hook("find", self)
            else:
                text, ok = QInputDialog.getText(self, "Поиск по данным", "Текст:")
                if not ok: return None
        f = self.records.filter; f.terms = []; f.join_value = "or"
        if text:
            for fl in self.api.list_fields(): f.terms.append({"field": fl["name"], "op": "contains", "value": text})
        f._show(); return self.apply_filter()

    def goto(self, target=None):
        if target is None:
            if ask_hook is not None: target = ask_hook("goto", self)
            else:
                target, ok = QInputDialog.getText(self, "Перейти к положению", "Номер строки или #ID:")
                if not ok: return None
        s = str(target).strip()
        if s.startswith("#"): return self._select_person(int(s[1:]))
        try: n = int(s)
        except ValueError: return False
        if 1 <= n <= self.records.proxy.rowCount():
            self.records.view.selectRow(n - 1); return True
        return False

    def _checkbox_queue(self, pid):
        """Чекбокс «Печать»: выделить запись и вызвать тот же QAction act_queue_toggle."""
        self._select_person(pid); self.act_queue_toggle.setEnabled(True); self.act_queue_toggle.trigger()

    def queue_toggle(self):
        ids = self.records.selected_ids()
        if not ids: return None
        rows = {p["id"]: p for p in self.records.model.rows}
        val = not all(rows[i]["print_mark"] for i in ids if i in rows)
        n = self.api.set_print_mark(ids, val); self._reload_keep(ids)
        self.statusBar().showMessage(("В очереди: " if val else "Убрано из очереди: ") + str(len(ids))); return val

    def mark_printed(self):
        ids = self.records.selected_ids()
        if not ids: return None
        n = self.api.mark_printed(ids); self._reload_keep(ids); return n

    def mark_unprinted(self):
        ids = self.records.selected_ids()
        if not ids: return None
        n = self.api.clear_printed(ids); self._reload_keep(ids); return n

    def _reload_keep(self, ids):
        self.records.reload()
        from PyQt6.QtCore import QItemSelectionModel
        sm = self.records.view.selectionModel()
        for pid in ids:
            r = self.records.model.row_of(pid)
            if r >= 0:
                sm.select(self.records.proxy.mapFromSource(self.records.model.index(r, 0)),
                          QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        self._sync_selection()

    def _copy_project_name(self):
        p = Path(str(self.api.db_path))
        if not p or str(p) in (":memory:", "", "."):
            return "проект_копия.db"
        suf = p.suffix or ".db"
        return str(p.with_name(f"{p.stem}_копия{suf}"))

    def _ask_path(self, kind, title, save=True, filt="SQLite (*.db *.sqlite)"):
        if ask_hook is not None: return ask_hook(kind, self)
        start = self._copy_project_name() if kind == "save_as" else str(self.api.db_path)
        f = QFileDialog.getSaveFileName if save else QFileDialog.getOpenFileName
        p, _ = f(self, title, start, filt); return p or None

    def new_project(self, path=None):
        path = path or self._ask_path("new", "Новый проект (файл БД)")
        if not path: return None
        if os.path.exists(path):
            QMessageBox.warning(self, "Новый проект", "Файл уже существует — используйте «Открыть»."); return None
        self.switch_db(path); return path

    def open_db(self, path=None):
        path = path or self._ask_path("open", "Открыть проект", save=False)
        if path: self.switch_db(path)
        return path

    def connect_db(self, path=None):
        if path is None and ask_hook is None:
            path, _ = QFileDialog.getSaveFileName(self, "Подключить или создать БД", str(self.api.db_path),
                                                  "SQLite (*.db *.sqlite)", options=QFileDialog.Option.DontConfirmOverwrite)
        path = path or (ask_hook("connect", self) if ask_hook else None)
        if path: self.switch_db(path)
        return path

    def disconnect_db(self):
        self.switch_db(":memory:")
        self.statusBar().showMessage("БД отключена: открыта временная база в памяти")

    def set_project_dirty(self, dirty=True):
        """Для тестов/скриншотов: принудительный «*». None-сброс — снова session.is_dirty()."""
        self._dirty_override = bool(dirty)
        if not dirty:
            sess = getattr(self.api, "session", None)
            if sess is not None:
                sess._mark_clean()
            self._dirty_override = False
        self._update_title()
        return self.is_project_dirty()

    def is_project_dirty(self):
        if getattr(self, "_dirty_override", None) is not None:
            return bool(self._dirty_override)
        sess = getattr(self.api, "session", None)
        if sess is not None: return bool(sess.is_dirty())
        return False

    def _sync_api_from_session(self):
        sess = getattr(self.api, "session", None)
        if sess is None: return
        self.api.con = sess.con
        if sess.source_path is not None:
            self.api.db_path = sess.source_path
            self.api.base_dir = str(sess.base_dir)

    def _after_template_committed(self):
        tt = getattr(self, "template_tools", None)
        if tt is not None and tt.template_mode:
            tt._saving = True
            try: tt.set_template_mode(False)
            finally: tt._saving = False
            if tt.editor is not None: tt.editor.reload()

    def save_project(self):
        """session.save(); в режиме шаблона TemplateEditActiveError → вопрос и save(commit_template=True)."""
        sess = getattr(self.api, "session", None)
        if sess is None:
            return None
        if sess.source_path is None:
            return self.save_as()
        try:
            r = sess.save()
        except TemplateEditActiveError:
            if not stage15.ask_save_template_and_project(self):
                return None
            try:
                r = sess.save(commit_template=True)
            except ProjectSaveError as e:
                stage15.show_save_error(self, e); return None
            self._after_template_committed()
        except ProjectSaveError as e:
            stage15.show_save_error(self, e); return None
        except ValueError as e:
            if "save_as" in str(e):
                return self.save_as()
            stage15.show_save_error(self, e); return None
        self._dirty_override = None
        self._sync_api_from_session(); self._update_title()
        self.statusBar().showMessage("Проект сохранён")
        return r

    def _bind_font(self, e):
        e.blockSignals(True); e.clear()
        try: families = list(self.api.list_font_families())
        except Exception: families = []
        e.addItems(families)
        e.blockSignals(False)
        e.currentTextChanged.connect(lambda name: self._set_template_style({"font_family": name}))

    def _bind_padding(self, e):
        e.editingFinished.connect(lambda e=e: self._set_template_style({"padding": e.value()}))

    def sync_template_style(self):
        if not hasattr(self, "act_font"): return None
        try: st = self.api.get_template_style() or {}
        except Exception: st = {}
        fam, pad = st.get("font_family") or "", st.get("padding")
        for w in self.act_font.widgets:
            w.blockSignals(True)
            if fam:
                i = w.findText(fam)
                if i < 0: w.addItem(fam); i = w.findText(fam)
                if i >= 0: w.setCurrentIndex(i)
            w.blockSignals(False)
        if pad is not None:
            for w in self.act_padding.widgets:
                w.blockSignals(True); w.setValue(int(pad)); w.blockSignals(False)
        return st

    def _set_template_style(self, style):
        tt = getattr(self, "template_tools", None)
        if tt is None or not tt.template_mode:
            from .layout_editor import _warn
            _warn(self, "Стиль шаблона", "Включите «Режим шаблона» на ленте, чтобы изменять шаблон")
            self.sync_template_style(); return None
        try: r = self.api.set_template_style(style)
        except ValueError as e:
            QMessageBox.warning(self, "Стиль шаблона", str(e)); self.sync_template_style(); return None
        self.layout_editor.reload(); return r

    def offer_template_restore(self):
        """Второй шаг восстановления: снимок шаблона. Рабочую копию спрашивают раньше, в open/switch_db."""
        api = self.api
        if api is None or not hasattr(api, "get_template_edit_state"): return None
        st = api.get_template_edit_state()
        if st is None: return None
        choice = stage15.ask_restore_template(self, st)
        if choice == "restore": api.cancel_template_edit()
        elif choice == "keep": api.commit_template_edit()
        else: return st
        self.refresh_all(); return choice

    def save_as(self, dest=None):
        dest = dest or self._ask_path("save_as", "Сохранить как…")
        if not dest: return None
        sess = getattr(self.api, "session", None)
        if sess is None:
            stage15.show_save_error(self, "нет открытой сессии проекта"); return None
        try:
            r = sess.save_as(dest, overwrite=True)
        except TemplateEditActiveError:
            if not stage15.ask_save_template_and_project(self):
                return None
            try:
                r = sess.save_as(dest, overwrite=True, commit_template=True)
            except (ProjectSaveError, ValueError, FileExistsError) as e:
                stage15.show_save_error(self, e); return None
        except (ProjectSaveError, ValueError, FileExistsError) as e:
            stage15.show_save_error(self, e); return None
        self.api.adopt_session(sess)
        self._after_template_committed()
        self._dirty_override = None
        if str(self.api.db_path) != ":memory:":
            self.settings.setValue("db_path", str(self.api.db_path))
        self.refresh_all(); self.statusBar().showMessage(f"Проект сохранён как: {self.api.db_path}")
        return r

    def compact(self, backup_dir=None):
        if backup_dir is None:
            backup_dir = ask_hook("compact", self) if ask_hook else QFileDialog.getExistingDirectory(
                self, "Папка для бэкапа", self.api.base_dir)
        if not backup_dir: return None
        r = self.api.compact_and_backup(backup_dir)
        self.statusBar().showMessage(f"БД сжата: {r.get('size_before')} → {r.get('size_after')} байт; бэкап: {r.get('backup')}")
        return r

    def restore(self, backup=None):
        backup = backup or self._ask_path("restore", "Восстановить из бэкапа", save=False, filt="Бэкап БД (*.db *.sqlite *.bak);;Все (*)")
        if not backup: return None
        if ask_hook is None and QMessageBox.question(
                self, "Восстановление", "Текущая БД будет заменена бэкапом. Продолжить?") != QMessageBox.StandardButton.Yes:
            return None
        self.api.restore_from(backup); self.refresh_all(); self._update_title(); return backup

    def field_manager(self, exec_=True):
        d = FieldManager(self.api, self)
        if exec_: d.exec(); self.refresh_all()
        return d

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

    def show_print_queue(self, exec_=True):
        d = PrintQueueDialog(self.api, self)
        if exec_: d.exec(); self.records.reload()
        return d

    def help(self):
        if ask_hook is not None: ask_hook("help", self)
        else: QMessageBox.information(self, "Справка", HELP_TEXT)
        return HELP_TEXT

    def about(self):
        text = ("Генератор пропусков\nРедактор шаблонов карт CR80, база записей, печать и экспорт.\n"
                f"Схема БД: v{self.api.schema_version()}")
        if about_hook is not None: about_hook(text)
        else: QMessageBox.about(self, "О программе", text)
        return text

    def _update_title(self):
        star = "* " if self.is_project_dirty() else ""
        self.setWindowTitle(f"{star}Генератор пропусков — {self.api.db_path}")
        self.statusBar().showMessage(f"БД: {self.api.db_path}; база путей фото: {self.api.base_dir}")

    def refresh_all(self):
        self._suspend_sel = True
        try:
            self.records.reload()
        finally:
            self._suspend_sel = False
        pid = self.selected_person_id()
        if self.stack.currentWidget() is self.layout_editor:
            self.layout_editor._set_person_meta(pid)
            self.layout_editor.reload()
            self.preview_panel.person_id = pid
        else:
            self.layout_editor._set_person_meta(pid)
            self.preview_panel.set_person(pid)
        self.sync_template_style(); self._update_title()

    def _open_api(self, path):
        """Создать BackendAPI; единственное место вопроса о рабочей копии при старте."""
        try:
            return BackendAPI(path)
        except RecoverableProjectError as e:
            ans = stage15.ask_recover_work(self)
            if ans is None:
                return BackendAPI(":memory:")
            inst = BackendAPI.__new__(BackendAPI)
            inst.con = None; inst.session = None
            inst.adopt_session(recover(e.info, accept=bool(ans)))
            return inst
        except ProjectLockedError:
            stage15.show_project_locked(self)
            return BackendAPI(":memory:")

    def _attach_session(self, path):
        """Открыть path в текущем api: сначала рабочая копия (RecoverableProjectError), без второго такого же вопроса."""
        try:
            self.api.open_db(path)
            return True
        except RecoverableProjectError as e:
            ans = stage15.ask_recover_work(self)
            if ans is None: return False
            self.api.adopt_session(recover(e.info, accept=ans))
            return True
        except ProjectLockedError:
            stage15.show_project_locked(self); return False
        except (FileNotFoundError, FileExistsError, OSError, ValueError) as e:
            QMessageBox.warning(self, "Проект", str(e)); return False

    def switch_db(self, path):
        if not self._attach_session(path): return None
        if str(self.api.db_path) != ":memory:": self.settings.setValue("db_path", str(self.api.db_path))
        self.clipboard = None; self._dirty_override = None
        self.refresh_all(); self._update_title()
        self.offer_template_restore()   # после рабочей копии — снимок шаблона, если он есть

    def do_import(self):
        ImportDialog(self.api, self).exec(); self.refresh_all()

    def do_export(self):
        ExportDialog(self.api, self.records.selected_ids(), self, filtered_ids=self.records.visible_ids()).exec()

    def do_print(self, _=False, printer=None, sides=("front", "back")):
        """QPrintDialog → предпроверка фото → snapshot (GUI) → print_snapshot в главном потоке.
        Печатаются только записи с print_mark=1. Возвращает (result, error)."""
        from PyQt6.QtPrintSupport import QPrinter, QPrintDialog
        ids = [p["id"] for p in self.api.list_persons(only_marked=True)]
        if not ids:
            QMessageBox.information(self, "Печать", "Нет записей, отмеченных для печати."); return None, None
        ask = printer is None
        if ask:
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        setup_printer(printer)   # до QPrintDialog: страница CR80, не A4 (CR80 / FuzzyMatch)
        if ask:
            if QPrintDialog(printer, self).exec() != QPrintDialog.DialogCode.Accepted: return None, None
            choice, ok = QInputDialog.getItem(self, "Печать", "Стороны:", ["Обе", "Лицевая", "Оборотная"], 0, False)
            if not ok: return None, None
            sides = {"Обе": ("front", "back"), "Лицевая": ("front",), "Оборотная": ("back",)}[choice]
        go, allow = confirm_missing_photos(self, self.api, ids)
        if not go:
            self.statusBar().showMessage("Печать отменена: есть записи без фото"); return None, None
        snap = self.api.snapshot(ids, sides)
        res, err = run_print_job(self, "Печать", print_snapshot, snap, printer, self.api.base_dir,
                                    allow_missing_photo=allow)
        msg = describe_result(res, err, "Печать")
        self.statusBar().showMessage(msg)
        if err is not None: QMessageBox.warning(self, "Печать", msg)
        elif res is not None and not getattr(res, "cancelled", False) and int(res) > 0:
            printed = list(dict.fromkeys(item["person"]["id"] for item in snap))
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
        if not yes: return 0
        changed = self.api.mark_printed(ids)
        self.records.reload(); self.statusBar().showMessage(f"Отметки сняты: {changed}"); return changed

    def closeEvent(self, ev):
        sess = getattr(self.api, "session", None)
        dirty = self.is_project_dirty()
        # Вопрос «Сохранить изменения?» — своё окно приложения или явный test hook.
        # Иначе w.close() в самотесте/смоуке зависает на модальном диалоге (сессия общая и dirty).
        if dirty and (self._own_api or stage15.save_changes_hook is not None):
            ans = stage15.ask_save_changes(self)
            if ans is None:
                ev.ignore(); return
            if ans is True:
                r = self.save_project()
                if r is None and self.is_project_dirty():
                    ev.ignore(); return
            elif self._own_api and sess is not None:
                try: sess.close(save=False)
                except Exception:
                    try: sess.discard()
                    except Exception: pass
                self.api.session = None; self.api.con = None
        elif self._own_api and sess is not None:
            try:
                sess.close()
            except UnsavedChangesError:
                ans = stage15.ask_save_changes(self)
                if ans is None:
                    ev.ignore(); return
                try: sess.close(save=bool(ans))
                except TemplateEditActiveError:
                    if not stage15.ask_save_template_and_project(self):
                        ev.ignore(); return
                    try: sess.close(save=bool(ans), commit_template=True)
                    except ProjectSaveError as e:
                        stage15.show_save_error(self, e); ev.ignore(); return
                except ProjectSaveError as e:
                    stage15.show_save_error(self, e); ev.ignore(); return
            self.api.session = None; self.api.con = None
        self.save_layout()          # расположение окна сохраняется автоматически
        if self._own_api and getattr(self.api, "con", None) is not None: self.api.close()
        QThreadPool.globalInstance().waitForDone(8000)
        super().closeEvent(ev)
