"""Снимки замечаний Ивана (11.11) для Windows CI.

Запуск: python ui/qa_screens.py
QT_QPA_PLATFORM=offscreen, демо-проект во временной папке, PNG в reports/screens/.
Если функции Backend ещё нет, скрипт не падает: сохраняет PNG с подписью «нет функции X».
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "reports" / "screens"


def _ensure_out():
    OUT.mkdir(parents=True, exist_ok=True)


def _save_label(path: Path, text: str, w=720, h=200):
    from PyQt6.QtWidgets import QLabel
    from PyQt6.QtCore import Qt
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    lab.setStyleSheet("background:#fff; color:#222; padding:16px; font-size:14px;")
    lab.resize(w, h)
    lab.show()
    lab.grab().save(str(path))
    lab.close()
    return path


def _grab(widget, path: Path):
    if widget is None:
        _save_label(path, "нет виджета для снимка")
        return path
    widget.show()
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app:
        app.processEvents()
    pix = widget.grab()
    pix.save(str(path))
    return path


def _missing(path: Path, name: str, extra=""):
    msg = f"нет функции {name}"
    if extra:
        msg = f"{msg}\n{extra}"
    _save_label(path, msg)
    return path


def _build_demo(tmp: Path):
    from badge_backend import api as B
    from ui.backend_api import BackendAPI, CARD_W_UNITS, CARD_H_UNITS, _UPSERT_HAS_TYPE

    db = tmp / "demo.db"
    c = B.connect(str(db))
    fields = (
        ("last_name", "Фамилия", "text"),
        ("first_name", "Имя", "text"),
        ("photo", "Фото сотрудника", "image"),
        ("logo", "Эмблема", "image"),
    )
    for i, (n, lab, typ) in enumerate(fields):
        if _UPSERT_HAS_TYPE:
            B.upsert_field(c, n, lab, i, data_type=typ)
        else:
            B.upsert_field(c, n, lab, i)
    W, H = int(CARD_W_UNITS), int(CARD_H_UNITS)
    B.create_element(c, "text", 40, 40, 400, 80, static_value="Константный текст",
                     style={"font_size": 16, "color": "#000000", "bold": True, "italic": False})
    B.create_element(c, "field", 40, 140, 400, 70, field_name="last_name",
                     style={"font_size": 14, "color": "#003399", "italic": True})
    B.create_element(c, "field", 40, 220, 400, 70, field_name="first_name",
                     style={"font_size": 14, "color": "#000000"})
    B.create_element(c, "photo", 500, 80, 220, 280, field_name="photo")
    B.create_element(c, "rect", 20, 20, W - 40, H - 40,
                     style={"border_style": "solid", "border_color": "#888888", "border_width": 2},
                     z_order=0)
    pid = B.create_person(c, {"last_name": "Иванов", "first_name": "Иван"})
    c.close()
    api = BackendAPI(db, tmp)
    return api, pid


def _spin(app, ms=80):
    from PyQt6.QtCore import QTimer, QEventLoop
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    app.processEvents()


def shot_01_paths(app, w, path: Path):
    from PyQt6.QtWidgets import QFileDialog, QWidget, QVBoxLayout, QLabel
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QPixmap, QPainter
    lines = []
    folder = None
    try:
        from ui.backend_api import logs_dir
        lines.append(f"logs_dir: {logs_dir()}")
    except Exception as e:  # noqa: BLE001
        lines.append(f"нет функции logs_dir")
        lines.append(str(e))
    try:
        from ui.backend_api import projects_dir
        folder = str(projects_dir())
        lines.append(f"projects_dir: {folder}")
    except Exception as e:  # noqa: BLE001
        lines.append("нет функции projects_dir")
        lines.append(str(e))

    start = w._save_as_start() if hasattr(w, "_save_as_start") else None
    if not start:
        start = str(Path(folder or Path.cwd()) / "проект.csp")

    cap = QLabel("\n".join(lines))
    cap.setWordWrap(True)
    cap.setStyleSheet("background:#fff; color:#222; padding:12px; font-size:13px;")
    cap.resize(800, 110)
    cap.show()
    _spin(app, 40)
    cap_pm = cap.grab()
    cap.close()

    dlg = QFileDialog(None, "Сохранить как…", start)
    dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    dlg.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    dlg.setNameFilter("Badge Generator / Smart ID (*.csp)")
    dlg.resize(800, 480)
    dlg.show()
    _spin(app, 160)
    dlg_pm = dlg.grab()
    dlg.close()

    wdt = max(cap_pm.width(), dlg_pm.width())
    h = cap_pm.height() + dlg_pm.height()
    out = QPixmap(wdt, h)
    out.fill(Qt.GlobalColor.white)
    p = QPainter(out)
    p.drawPixmap(0, 0, cap_pm)
    p.drawPixmap(0, cap_pm.height(), dlg_pm)
    p.end()
    out.save(str(path))


def shot_03_bold(app, w, path: Path):
    le = w.layout_editor
    w.show_editor()
    if hasattr(w, "act_template_mode") and not getattr(getattr(w, "template_tools", None), "template_mode", False):
        w.act_template_mode.trigger()
        _spin(app, 80)
    text = next((i for i in le.items() if i.el.get("type") == "text"), None)
    if text is None:
        _save_label(path, "нет текстового объекта для снимка bold/italic")
        return
    le.select(text.el["id"])
    le.set_show_render(False)
    _spin(app, 80)
    op = w.props_dock.panel
    op.w_bold.setChecked(True)
    op.w_italic.setChecked(True)
    op.flush() if hasattr(op, "flush") else op._apply_font()
    _spin(app, 120)
    w.resize(1280, 800)
    w.show()
    _spin(app, 100)
    _grab(w, path)


def shot_04_table(app, w, path: Path):
    w.show_main()
    w.resize(1280, 800)
    w.show()
    _spin(app, 120)
    _grab(w, path)


def shot_05(app, w, path: Path, render_on: bool):
    w.show_editor()
    le = w.layout_editor
    if hasattr(w, "act_template_mode") and not getattr(getattr(w, "template_tools", None), "template_mode", False):
        w.act_template_mode.trigger()
        _spin(app, 80)
    bound = next((i for i in le.items() if i.el.get("field_name")), None)
    if bound is not None:
        le.select(bound.el["id"])
    le.set_show_render(bool(render_on))
    _spin(app, 200)
    w.resize(1280, 800)
    w.show()
    _spin(app, 150)
    _grab(w, path)


def shot_06_overlap(app, w, path: Path):
    w.show_editor()
    le = w.layout_editor
    items = le.items()
    if len(items) >= 2:
        a, b = items[0], items[1]
        try:
            w.api.update_element(a.el["id"], x=b.el["x"], y=b.el["y"])
        except Exception:  # noqa: BLE001
            pass
        le.load(le.side, a.el["id"])
    le.set_show_render(False)
    _spin(app, 120)
    w.resize(1280, 800)
    w.show()
    _spin(app, 100)
    _grab(w, path)


def shot_07_layer(app, w, path: Path):
    w.show_editor()
    le = w.layout_editor
    if hasattr(w, "act_template_mode") and not getattr(getattr(w, "template_tools", None), "template_mode", False):
        w.act_template_mode.trigger()
        _spin(app, 80)
    it = next((i for i in le.items() if i.el.get("type") != "rect"), None) or (le.items()[0] if le.items() else None)
    if it is not None:
        le.select(it.el["id"])
    op = w.props_dock.panel
    if hasattr(op, "g_layer"):
        op._set_group_visible(op.g_layer, True)
        op.g_layer.setExpanded(True)
    _spin(app, 80)
    # снимок панели свойств (группа «Слой» видна)
    w.resize(1280, 800)
    w.show()
    _spin(app, 100)
    target = w.props_dock if hasattr(w, "props_dock") else w
    _grab(target, path)


def main():
    _ensure_out()
    from PyQt6.QtCore import QCoreApplication
    from PyQt6.QtWidgets import QApplication

    QCoreApplication.setApplicationName("BadgeGenerator")
    tmp = Path(tempfile.mkdtemp(prefix="bg_qa_screens_"))
    os.environ["BG_APP_ROOT"] = str(tmp)
    from ui.backend_api import BackendAPI, missing_backend
    from ui.main_window import MainWindow
    app = QApplication.instance() or QApplication(sys.argv[:1])

    shots = {
        "01_logs_projects_dir.png": None,
        "03_bold_italic.png": None,
        "04_records_table.png": None,
        "05_editor_field_labels_render_off.png": None,
        "05_editor_field_labels_render_on.png": None,
        "06_overlap_no_red.png": None,
        "07_layer_group.png": None,
    }

    w = None
    try:
        api, pid = _build_demo(tmp)
        w = MainWindow(api)
        w.resize(1280, 800)
        w.show()
        _spin(app, 150)
        try:
            w._select_person(pid)
        except Exception:
            pass
        _spin(app, 100)

        runners = [
            ("01_logs_projects_dir.png", lambda p: shot_01_paths(app, w, p)),
            ("03_bold_italic.png", lambda p: shot_03_bold(app, w, p)),
            ("04_records_table.png", lambda p: shot_04_table(app, w, p)),
            ("05_editor_field_labels_render_off.png", lambda p: shot_05(app, w, p, False)),
            ("05_editor_field_labels_render_on.png", lambda p: shot_05(app, w, p, True)),
            ("06_overlap_no_red.png", lambda p: shot_06_overlap(app, w, p)),
            ("07_layer_group.png", lambda p: shot_07_layer(app, w, p)),
        ]
        for name, fn in runners:
            dest = OUT / name
            try:
                fn(dest)
                if not dest.exists():
                    _save_label(dest, f"снимок {name} не записан")
                print(f"OK {dest}")
            except LookupError as e:
                _save_label(dest, str(e) or missing_backend("?"))
                print(f"MISSING {dest}: {e}")
            except Exception as e:  # noqa: BLE001
                tb = traceback.format_exc()
                _save_label(dest, f"ошибка снимка {name}:\n{e}\n{tb[-800:]}", w=800, h=400)
                print(f"ERR {dest}: {e}")
    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc()
        for name in shots:
            dest = OUT / name
            if not dest.exists():
                _save_label(dest, f"ошибка подготовки демо:\n{e}\n{tb[-800:]}", w=800, h=400)
        print(f"FATAL {e}")
        return 0  # скрипт не должен валить CI (continue-on-error тоже есть)
    finally:
        if w is not None:
            w.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
