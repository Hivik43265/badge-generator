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
# Этап 14: Haar-каскад лица для detect_face_crop → <_MEIPASS>/cv2/data/ (photo_edit.cascade_path ищет там в exe)
try:
    import cv2 as _cv2
    _casc = os.path.join(_cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
except ImportError as _e:
    raise SystemExit(f"ERROR: opencv-python-headless not installed ({_e}): face detection is required (D47)")
if not os.path.isfile(_casc):
    raise SystemExit(f"ERROR: {_casc} not found (opencv>=5 wheels ship no cascades; need opencv-python-headless>=4.8,<5)")
datas.append((_casc, os.path.join("cv2", "data")))
# D47: встроенное фото для --self-test → <_MEIPASS>/badge_backend/assets/selftest_face.jpg
datas.append((os.path.join(ROOT, "badge_backend", "assets", "selftest_face.jpg"), os.path.join("badge_backend", "assets")))
hidden = collect_submodules("badge_backend") + collect_submodules("barcode") + ["qrcode.image.pil"]
# Этап 13 / D22: аудит hiddenimports. Модули ui/ импортируются статически из main_window (PyInstaller
# находит их сам), но ленивые импорты внутри функций (QtMultimedia в main_view.camera_available /
# CameraDialog, QtPrintSupport) перечислены явно, чтобы сборка не зависела от анализа байткода.
# Плагины multimedia (бэкенд ffmpeg/windowsmediafoundation) собирает штатный хук PyInstaller
# hook-PyQt6.QtMultimedia, когда модуль попадает в граф — поэтому он здесь обязателен.
hidden += [m for m in collect_submodules("ui") if m != "ui.smoke_test"]
hidden += ["PyQt6.QtMultimedia", "PyQt6.QtMultimediaWidgets", "PyQt6.QtPrintSupport", "PyQt6.sip"]
hidden += collect_submodules("openpyxl") + ["xlrd", "xlwt"]
hidden += ["cv2", "numpy"]   # этап 14: импорт ленивый (внутри detect_face_crop)

# --- Qt-плагины и DLL (камера D22, печать, jpeg). Ищем в установленном PyQt6 (PyQt6/Qt6/{bin,plugins}),
# кладём по тем же относительным путям, что и штатные хуки PyInstaller (PyQt6/Qt6/...), только если файл есть.
# Отчёт — dist/BadgeGenerator.bundle.txt (FOUND/MISSING), его проверяет CI. Сборку не роняем: CI решает.
import glob, sys
REQUIRED_QT = [   # (подкаталог Qt6, шаблон файла)
    ("plugins/multimedia", "ffmpegmediaplugin.dll"), ("plugins/multimedia", "windowsmediaplugin.dll"),
    ("plugins/platforms", "qwindows.dll"), ("plugins/imageformats", "qjpeg.dll"),
    ("plugins/printsupport", "windowsprintersupport.dll"),
    ("bin", "Qt6Multimedia.dll"), ("bin", "Qt6MultimediaWidgets.dll"),
    ("bin", "avcodec*.dll"), ("bin", "avformat*.dll"), ("bin", "avutil*.dll"),
    ("bin", "swresample*.dll"), ("bin", "swscale*.dll"),
]
qt_binaries, _qt_report = [], []
try:
    import PyQt6
    QT6 = os.path.join(os.path.dirname(PyQt6.__file__), "Qt6")
except ImportError:
    QT6 = None
for sub, pat in REQUIRED_QT:
    hits = sorted(glob.glob(os.path.join(QT6, *sub.split("/"), pat))) if QT6 else []
    for h in hits: qt_binaries.append((h, "PyQt6/Qt6/" + sub))
    _qt_report.append(("FOUND" if hits else "MISSING", f"{sub}/{pat}", [os.path.basename(h) for h in hits]))
_missing = [r[1] for r in _qt_report if r[0] == "MISSING"]
if _missing:
    print("WARNING: Qt files not found in " + str(QT6) + ": " + ", ".join(_missing), file=sys.stderr)
excludes = ["data_tools", "pytest", "tkinter"]   # data_tools — опционален (fallback-валидатор)


def _analysis(script, extra_excludes=(), binaries=()):
    return Analysis([os.path.join(ROOT, script)], pathex=[ROOT], binaries=list(binaries), datas=datas,
                    hiddenimports=hidden, hookspath=[], runtime_hooks=[],
                    excludes=excludes + list(extra_excludes), noarchive=False)



def _exe(a, name, console):
    pyz = PYZ(a.pure)
    return EXE(pyz, a.scripts, a.binaries, a.datas, [], name=name, icon=ICON,
               debug=False, strip=False, upx=False, runtime_tmpdir=None,
               console=console, disable_windowed_traceback=False)


a_app = _analysis("main.py", binaries=list(qt_binaries))
# OpenCV videoio-FFmpeg (~20–30 МБ) не нужен: камера идёт через QtMultimedia, cv2 — только Haar по картинке
a_app.binaries = [b for b in a_app.binaries if "opencv_videoio_ffmpeg" not in os.path.basename(str(b[0])).lower()]
app = _exe(a_app, "BadgeGenerator", console=False)

a_smoke = _analysis(os.path.join("packaging", "smoke_entry.py"), extra_excludes=["PyQt6", "ui", "cv2"])
smoke = _exe(a_smoke, "BadgeSmoke", console=True)

# Отчёт о Qt-файлах для CI (dist/BadgeGenerator.bundle.txt): по строке на шаблон "FOUND|MISSING<TAB>шаблон<TAB>файлы"
_dist = os.path.join(ROOT, "dist"); os.makedirs(_dist, exist_ok=True)
_names = {os.path.basename(str(t[0])).lower() for t in a_app.binaries}   # TOC: (dest_name, src, typecode)
with open(os.path.join(_dist, "BadgeGenerator.bundle.txt"), "w", encoding="utf-8") as f:
    for st, pat, files in _qt_report:
        inb = [n for n in files if n.lower() in _names]
        f.write(f"{'FOUND' if inb else 'MISSING'}\t{pat}\t{','.join(inb)}\n")
    _casc_in = any(str(t[0]).replace("\\", "/").endswith("cv2/data/haarcascade_frontalface_default.xml") for t in a_app.datas)
    f.write(f"{'FOUND' if _casc_in else 'MISSING'}\tcv2/data/haarcascade_frontalface_default.xml\t\n")
    _cv2_in = [os.path.basename(str(t[0])) for t in a_app.binaries
               if str(t[0]).replace("\\", "/").lower().startswith("cv2/") and str(t[0]).lower().endswith((".pyd", ".so"))]
    f.write(f"{'FOUND' if _cv2_in else 'MISSING'}\tcv2\t{','.join(_cv2_in)}\n")
    _st_in = any(str(t[0]).replace("\\", "/").endswith("badge_backend/assets/selftest_face.jpg") for t in a_app.datas)
    f.write(f"{'FOUND' if _st_in else 'MISSING'}\tbadge_backend/assets/selftest_face.jpg\t\n")
