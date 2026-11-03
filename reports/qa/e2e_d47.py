"""QA D47: (а) регрессионный тест ловит удерживаемое соединение; (б) ImportDialog переживает исключение из Sheet.close().
QT_QPA_PLATFORM=offscreen .venv/bin/python reports/qa/e2e_d47.py"""
import os, sys, json, sqlite3, tempfile, pathlib
from contextlib import closing
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen"); sys.dont_write_bytecode = True
ROOT = pathlib.Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))
from PIL import Image
from PyQt6.QtWidgets import QApplication
app = QApplication.instance() or QApplication(sys.argv)
from badge_backend import api as bapi
from badge_backend.services.sources import Sheet
from badge_backend.testing import create_legacy_db
from ui.backend_api import BackendAPI
from ui.dialogs import ImportDialog
from ui.main_window import MainWindow
TMP = pathlib.Path(tempfile.mkdtemp(prefix="bgqa47_")); RES = []
def chk(n, ok, ev=""): RES.append((n, bool(ok), str(ev))); print("PASS" if ok else "FAIL", "|", n, "|", ev)
def fds(path):
    t = os.path.realpath(path); out = []
    for fd in os.listdir("/proc/self/fd"):
        try:
            if os.path.realpath(os.readlink(f"/proc/self/fd/{fd}")).startswith(t): out.append(fd)
        except OSError: pass
    return out

# (а) удерживаемое соединение к work_path видно в /proc/self/fd (метод теста test_db_import_leaves_no_open_handles)
p = create_legacy_db(TMP / "v1.db", version=1)
sh = bapi.open_source(p); w = sh[0].work_path
chk("Без утечки: дескрипторов на work_path нет", fds(w) == [], fds(w))
leak = sqlite3.connect(str(w)); leak.execute("SELECT 1").fetchall()
chk("Инъекция утечки: метод теста её обнаруживает", fds(w) != [], fds(w))
leak.close(); sh[0].close()

# (б) Sheet.close() бросает → диалог импорта не падает
a = BackendAPI(TMP / "p.db", TMP); a.upsert_field("a", "A", 0, data_type="text")
mw = MainWindow(a); mw.show(); app.processEvents()
src = create_legacy_db(TMP / "src.db", version=4)
with closing(sqlite3.connect(src)) as c:
    c.execute("INSERT INTO person_fields(name,label,sort_order) VALUES ('a','A',0)"); c.execute("INSERT INTO persons(fields_json) VALUES (?)", (json.dumps({"a": "x"}),)); c.commit()
orig = Sheet.close
def boom(self): raise PermissionError("busy (QA D47)")
for how in ("set_file", "reject", "closeEvent"):
    d = ImportDialog(a, mw); ok_open = d.set_file(str(src)) is not False; wp = d.current_sheet().work_path
    Sheet.close = boom; err = None
    try:
        if how == "set_file": d.set_file(str(src))
        elif how == "reject": d.reject()
        else: d.close()
        app.processEvents()
    except Exception as e: err = e  # noqa: BLE001
    finally: Sheet.close = orig
    chk(f"Sheet.close() бросает при {how}: диалог не падает", ok_open and err is None, err)
    msg = d.log.toPlainText()
    chk(f"Sheet.close() бросает при {how}: ошибка показана пользователю", "busy" in msg or "Не удалось" in msg, repr(msg[-120:]))
    try: d.close_sheets(); d.deleteLater()
    except Exception: pass  # noqa: BLE001
    for s in list(TMP.glob("**/*")): pass

# ---- D48 ----
import subprocess, time, tempfile as _tf
from badge_backend.services import sources as S
from badge_backend import db as DB
d = ImportDialog(a, mw); d.set_file(str(src)); wp = pathlib.Path(d.current_sheet().work_path)
chk("D48: рабочая копия в <tmp>/BadgeGenerator-import/bg_import_*.db", wp.parent.name == "BadgeGenerator-import" and wp.name.startswith("bg_import_"), wp)
n = {"c": 0}
def once(self):
    n["c"] += 1
    if n["c"] == 1: raise PermissionError("busy (QA D48)")
    return orig(self)
Sheet.close = once
try: d.reject(); err = None
except Exception as e: err = e  # noqa: BLE001
finally: Sheet.close = orig
chk("D48: OSError при закрытии → в журнале по-русски с именем файла", err is None and wp.name in d.log.toPlainText() and "Не удалось" in d.log.toPlainText(), d.log.toPlainText()[-160:])
chk("D48: при закрытии диалога один повтор close() удаляет копию", n["c"] == 2 and not wp.exists(), (n, wp.exists()))
def rt(self): raise RuntimeError("не OSError")
d = ImportDialog(a, mw); d.set_file(str(src)); Sheet.close = rt
try: d.close_sheets(); err = None
except RuntimeError as e: err = e
finally: Sheet.close = orig; d.close_sheets()
chk("D48: не-OSError не глотается", isinstance(err, RuntimeError), err)
# сквозной: close() не смог → копия осталась → «перезапуск» (новый процесс) удаляет старую
d = ImportDialog(a, mw); d.set_file(str(src)); wp = pathlib.Path(d.current_sheet().work_path)
Sheet.close = boom
try: d.reject()
finally: Sheet.close = orig
left = wp.exists(); old = time.time() - 7 * 3600; os.utime(wp, (old, old))
wd = wp.parent; foreign = wd / "other_keep.db"; foreign.write_bytes(b"x"); os.utime(foreign, (old, old))
fresh = wd / "bg_import_qa_fresh.db"; fresh.write_bytes(b"x")
root_old = pathlib.Path(_tf.gettempdir()) / "bg_import_qa_rootold.db"; root_old.write_bytes(b"x"); os.utime(root_old, (old, old))
_r = pathlib.Path(_tf.gettempdir())
root_sidecars = [_r / f"bg_import_qa_rootold.db{x}" for x in ("-journal", "-wal", "-shm")]
for x in root_sidecars: x.write_bytes(b"x"); os.utime(x, (old, old))
root_fresh = _r / "bg_import_qa_rootfresh.db"; root_fresh.write_bytes(b"x")
root_other = _r / "qa_other_keep.db"; root_other.write_bytes(b"x"); os.utime(root_other, (old, old))
root_odd = _r / "bg_import_qa_keep.txt"; root_odd.write_bytes(b"x"); os.utime(root_odd, (old, old))
code = f"import sys; sys.path.insert(0, {str(ROOT)!r}); from ui.backend_api import BackendAPI; BackendAPI({str(TMP / 'r.db')!r}, {str(TMP)!r})"
r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
chk("D48 сквозной: close() упал → копия осталась → перезапуск удалил её", left and r.returncode == 0 and not wp.exists(), (left, r.returncode, wp.exists(), r.stderr[-200:]))
chk("D48: чужой файл и свежая копия (<6 ч) не тронуты", foreign.exists() and fresh.exists(), (foreign.exists(), fresh.exists()))
rr = pathlib.Path(_tf.gettempdir())
chk("D48.5: старые bg_import_*.db в корне tempdir удалены", not root_old.exists(), root_old)
chk("D48.5: свежая копия в корне и чужое имя в корне не тронуты", root_fresh.exists() and root_other.exists() and root_odd.exists(), (root_fresh.exists(), root_other.exists(), root_odd.exists()))
chk("D48.5: -journal/-wal/-shm старой копии в корне удалены", not any(x.exists() for x in root_sidecars), [x.exists() for x in root_sidecars])
for f in (foreign, fresh, root_old, root_fresh, root_other, root_odd, *root_sidecars): f.unlink(missing_ok=True)
code2 = f"import sys; sys.path.insert(0, {str(ROOT)!r}); import badge_backend.services.sources as S; S._cleanup_stale_work_copies=lambda *a,**k: 1/0; from ui.backend_api import BackendAPI; BackendAPI({str(TMP / 'r2.db')!r}, {str(TMP)!r}); print('OK')"
r = subprocess.run([sys.executable, "-c", code2], capture_output=True, text=True)
chk("D48: ошибка очистки не ломает старт", r.returncode == 0 and "OK" in r.stdout, (r.returncode, r.stderr[-200:]))

# ---- D48 (b): журнал повтора ----
def mk():
    dd = ImportDialog(a, mw); dd.set_file(str(src)); return dd, pathlib.Path(dd.current_sheet().work_path)
dd, wp = mk(); Sheet.close = boom
try: dd.reject()
finally: Sheet.close = orig
L = [l for l in dd.log.toPlainText().splitlines() if wp.name in l]
chk("D48b: оба сбоя → полная первая строка + одна краткая «Повторная попытка закрыть <файл> не удалась»",
    len(L) == 2 and "busy" in L[0] and L[1] == f"Повторная попытка закрыть {wp.name} не удалась", L)
Sheet.close = orig; dd.close_sheets(); wp.unlink(missing_ok=True)
dd, wp = mk(); n = {"c": 0}; Sheet.close = once
try: dd.reject()
finally: Sheet.close = orig
L = [l for l in dd.log.toPlainText().splitlines() if wp.name in l]
chk("D48b: повтор успешен → только первая строка, лишней нет", len(L) == 1 and "busy" in L[0] and not wp.exists(), L)
print(f"ИТОГО: {sum(r[1] for r in RES)}/{len(RES)} PASS; tmp={TMP}")
