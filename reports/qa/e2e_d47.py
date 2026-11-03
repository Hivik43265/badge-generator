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
print(f"ИТОГО: {sum(r[1] for r in RES)}/{len(RES)} PASS; tmp={TMP}")
