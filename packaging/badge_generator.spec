# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec, этап 11. Запуск из корня репозитория:
#   pyinstaller --noconfirm --clean packaging/badge_generator.spec
# Результат: dist/BadgeGenerator(.exe) — GUI (onefile, windowed, иконка),
#            dist/BadgeSmoke(.exe)     — консольный смоук backend (packaging/smoke_entry.py).
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))
ICON = os.path.join(SPECPATH, "icon.ico")

datas = [(os.path.join(ROOT, "badge_backend", "schema.sql"), "badge_backend")]
datas += collect_data_files("barcode")   # шрифты python-barcode (ImageWriter)
datas += collect_data_files("qrcode")
hidden = collect_submodules("badge_backend") + collect_submodules("barcode") + ["qrcode.image.pil"]
# Этап 13 / D22: аудит hiddenimports. Модули ui/ импортируются статически из main_window (PyInstaller
# находит их сам), но ленивые импорты внутри функций (QtMultimedia в main_view.camera_available /
# CameraDialog, QtPrintSupport) перечислены явно, чтобы сборка не зависела от анализа байткода.
# Плагины multimedia (бэкенд ffmpeg/windowsmediafoundation) собирает штатный хук PyInstaller
# hook-PyQt6.QtMultimedia, когда модуль попадает в граф — поэтому он здесь обязателен.
hidden += [m for m in collect_submodules("ui") if m != "ui.smoke_test"]
hidden += ["PyQt6.QtMultimedia", "PyQt6.QtMultimediaWidgets", "PyQt6.QtPrintSupport", "PyQt6.sip"]
# Сценарий self-test (Контролёр) кладётся в exe, если он есть: sys._MEIPASS/qa/e2e_click_all.py
_E2E = os.path.join(ROOT, "reports", "qa", "e2e_click_all.py")
if os.path.exists(_E2E):
    datas.append((_E2E, "qa"))
excludes = ["data_tools", "pytest", "tkinter"]   # data_tools — опционален (fallback-валидатор)


def _analysis(script, extra_excludes=()):
    return Analysis([os.path.join(ROOT, script)], pathex=[ROOT], binaries=[], datas=datas,
                    hiddenimports=hidden, hookspath=[], runtime_hooks=[],
                    excludes=excludes + list(extra_excludes), noarchive=False)


def _exe(a, name, console):
    pyz = PYZ(a.pure)
    return EXE(pyz, a.scripts, a.binaries, a.datas, [], name=name, icon=ICON,
               debug=False, strip=False, upx=False, runtime_tmpdir=None,
               console=console, disable_windowed_traceback=False)


a_app = _analysis("main.py")
app = _exe(a_app, "BadgeGenerator", console=False)

a_smoke = _analysis(os.path.join("packaging", "smoke_entry.py"), extra_excludes=["PyQt6", "ui"])
smoke = _exe(a_smoke, "BadgeSmoke", console=True)
