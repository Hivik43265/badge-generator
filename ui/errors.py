"""Глобальный перехват исключений (D20): диалог + запись в error.log, приложение не падает.

Лог: badge_backend.app_paths.logs_dir()/error.log. Если функция Backend ещё не доступна,
сохраняется прежний путь QStandardPaths.AppDataLocation/error.log.
"""
import sys, os, datetime, traceback
from PyQt6.QtCore import QStandardPaths, QCoreApplication

APP_NAME = "BadgeGenerator"
error_hook = None        # тесты/самотест: error_hook(text) вместо модального окна
errors = []              # все перехваченные (для самотеста)


def _fallback_log_dir():
    if not QCoreApplication.applicationName(): QCoreApplication.setApplicationName(APP_NAME)
    d = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation) or os.path.expanduser(f"~/.{APP_NAME}")
    os.makedirs(d, exist_ok=True); return d


def log_dir():
    """Каталог журнала: app_paths.logs_dir(), иначе QStandardPaths."""
    try:
        from .backend_api import logs_dir as _be_logs
        d = _be_logs()
        if d:
            d = os.fspath(d)
            os.makedirs(d, exist_ok=True)
            return d
    except Exception:  # noqa: BLE001 — нет функции / ошибка Backend: пишем в прежний каталог
        pass
    return _fallback_log_dir()


def log_path():
    return os.path.join(log_dir(), "error.log")


def write_log(text):
    try:
        with open(log_path(), "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {text.rstrip()}\n\n")
    except OSError:
        pass


def handle(etype, value, tb):
    text = "".join(traceback.format_exception(etype, value, tb))
    errors.append(text); write_log(text)
    sys.__stderr__ and sys.__stderr__.write(text)
    if error_hook is not None: error_hook(text); return
    try:
        from PyQt6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance() is not None:
            QMessageBox.critical(None, "Ошибка", f"Произошла ошибка, приложение продолжит работу.\n\n{etype.__name__}: {value}\n\n"
                                 f"Подробности записаны в журнал:\n{log_path()}")
    except Exception:  # noqa: BLE001
        pass


def install():
    QCoreApplication.setApplicationName(APP_NAME)
    sys.excepthook = handle
