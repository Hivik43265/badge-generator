"""Встроенный самотест (`BadgeGenerator.exe --self-test`, из исходников: `python main.py --self-test`).

Основа — копия reports/qa/e2e_click_all.py (оригинал QA не меняется). Временная БД и временный QSettings;
1) нажать КАЖДЫЙ QAction ленты (+ act_align_*), модальные окна закрываются таймером;
2) открыть каждый диалог напрямую; 3) «добавить запись → текст на превью» (с полями и без person_fields).
Любое исключение (в т.ч. в слоте Qt, через sys.excepthook) → FAIL.

Опции: --log <путь> — файл лога (по умолчанию <AppData>/BadgeGenerator/self_test.log).
Сторожевой таймер 170 с → FAIL и код 1. excepthook в режиме самотеста модальных окон не показывает; любое исключение → код 1.
Лог: stdout и файл (Windows: %APPDATA%\\BadgeGenerator\\self_test.log), строки
    PASS | <проверка> | <доказательство>
    FAIL | <проверка> | <доказательство/трейсбек>
    ИТОГО: N/M PASS; исключений в слотах: K; tmp=<каталог>
Код выхода: 0 — все PASS, 1 — есть FAIL.
"""
import os, sys, tempfile, pathlib, traceback, datetime

WATCHDOG_S = 170


def run(argv=None, *, app=None, log_file=None, exit_process=False):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen") if "--show" not in (argv or []) else None
    from PyQt6.QtCore import QSettings
    from PyQt6.QtWidgets import QApplication
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="bg_selftest_"))
    QSettings.setPath(QSettings.Format.NativeFormat, QSettings.Scope.UserScope, str(tmp / "cfg"))
    app = app or QApplication.instance() or QApplication(list(argv or sys.argv[:1]))
    from . import errors
    errors.install()
    from . import main_view, photo_block

    argv = list(argv or [])
    if log_file is None and "--log" in argv and argv.index("--log") + 1 < len(argv): log_file = argv[argv.index("--log") + 1]
    log_file = os.path.abspath(log_file or os.path.join(errors.log_dir(), "self_test.log"))
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    # сторожевой таймер: процесс гарантированно завершится (код 1) не позже WATCHDOG_S секунд
    import threading
    def _watchdog():
        try:
            with open(log_file, "a", encoding="utf-8") as f: f.write(f"FAIL | watchdog | самотест не завершился за {WATCHDOG_S} с\n")
        finally:
            print(f"FAIL | watchdog | самотест не завершился за {WATCHDOG_S} с", flush=True); os._exit(1)
    wd = threading.Timer(WATCHDOG_S, _watchdog); wd.daemon = True; wd.start()
    logf = open(log_file, "w", encoding="utf-8")
    RES, EXC = [], []

    def out(line):
        print(line, flush=True); logf.write(line + "\n"); logf.flush()

    def chk(n, ok, ev=""):
        RES.append((n, bool(ok), str(ev))); out(f"{'PASS' if ok else 'FAIL'} | {n} | {ev}")

    old_hook, old_eh = errors.error_hook, sys.excepthook
    errors.error_hook = lambda text: EXC.append(text[-600:])
    sys.excepthook = errors.handle
    old_fm, old_file = main_view.field_manager_hook, photo_block.file_hook
    photo_block.file_hook = lambda _b: ""          # «Из файла…» → отмена

    from . import qa_click_all
    try:
        out(f"# BadgeGenerator self-test {datetime.datetime.now().isoformat(timespec='seconds')}; tmp={tmp}")
        qa_click_all.scenario(tmp, chk, out, EXC)
    except Exception:  # noqa: BLE001
        chk("самотест без исключений", False, traceback.format_exc()[-800:])
    finally:
        errors.error_hook, sys.excepthook = old_hook, old_eh
        main_view.field_manager_hook, photo_block.file_hook = old_fm, old_file
    passed = sum(r[1] for r in RES)
    wd.cancel()
    out(f"ИТОГО: {passed}/{len(RES)} PASS; исключений в слотах: {len(EXC)}; tmp={tmp}; лог={log_file}")
    logf.close()
    code = 0 if RES and passed == len(RES) and not EXC else 1      # любой FAIL или исключение (excepthook) → 1
    if exit_process: os._exit(code)
    return code


if __name__ == "__main__":
    sys.exit(run(sys.argv))
