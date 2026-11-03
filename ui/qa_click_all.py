"""Сценарий click-all (основа — reports/qa/e2e_click_all.py; не зависит от reports/).
Вызывается ui.self_test (временная БД/QSettings, --log, сторожевой таймер, excepthook — там).

scenario(tmp, chk, out, EXC): нажать каждый QAction ленты (+act_align_*), открыть каждый диалог (модальные закрываются
таймером), камера/фото внутри формы записи (D22), менеджер полей, «добавить запись → текст на превью»,
в конце — нет открытых модальных окон. chk(name, ok, evidence) пишет PASS/FAIL; EXC — список исключений из excepthook.
"""
import traceback, datetime
from PyQt6.QtCore import QTimer, QEventLoop, Qt
from PyQt6.QtGui import QAction, QImage, QColor
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QMenu


LATE = ("act_card_delete", "act_connect", "act_disconnect", "act_compact")


def run(argv=None):
    """Точка входа для reports/qa/e2e_click_all.py: временная БД, лог, сторожевой таймер — через ui.self_test. → код выхода."""
    from .self_test import run as _run
    return _run(list(argv or []))


def scenario(tmp, chk, out, EXC):
    from badge_backend import api as B
    from .backend_api import BackendAPI
    from .main_window import MainWindow
    def spin(ms=30):
        l = QEventLoop(); QTimer.singleShot(ms, l.quit); l.exec()

    OPENED, FILL, CAM = [], {}, []

    def closer():
        w = QApplication.activeModalWidget() or next((x for x in QApplication.topLevelWidgets() if isinstance(x, QDialog) and x.isVisible()), None)
        if w is None:
            for m in QApplication.topLevelWidgets():
                if isinstance(m, QMenu) and m.isVisible(): m.close()
            return
        OPENED.append(f"{type(w).__name__}«{w.windowTitle()}»")
        try:
            if FILL and type(w).__name__ == "RecordForm":
                for k, v in FILL.items():
                    e = getattr(w, "edits", {}).get(k)
                    if e is not None: e.setText(v)
                img = FILL.pop("__photo__", None)
                if img is not None and hasattr(w, "photo_block"):
                    # D22: снимок внутри добавления фото — тот же слот, что QImageCapture.imageCaptured
                    pb = w.photo_block; CAM.append(pb.has_camera); pb.set_captured(img)
                FILL.clear(); w.save(); return
            if isinstance(w, QMessageBox): w.done(QMessageBox.StandardButton.No.value if w.buttons() else 0); return
            if hasattr(w, "photo_block"): w.photo_block.stop()
            w.reject() if isinstance(w, QDialog) else w.close()
        except Exception:  # noqa: BLE001
            EXC.append(traceback.format_exc()[-600:])

    tm = QTimer(); tm.setInterval(80); tm.timeout.connect(closer); tm.start()

    def make_db(path, with_fields=True):
        c = B.connect(str(path))
        if with_fields:
            for i, (n, l) in enumerate((("last_name", "Фамилия"), ("first_name", "Имя"), ("faculty", "Факультет"))): B.upsert_field(c, n, l, i)
        for fn, y, h in (("last_name", 40, 120), ("first_name", 200, 100), ("faculty", 330, 90)):
            B.create_element(c, "field", 40, y, 900, h, field_name=fn)
        B.create_element(c, "rect", 20, 20, 970, 600, style={"stroke": "#000", "stroke_width": 2})
        B.create_element(c, "ellipse", 800, 450, 150, 120, style={"stroke": "#000", "stroke_width": 2})
        pid = B.create_person(c, {"last_name": "Иванов", "first_name": "Иван", "faculty": "Физфак"})
        c.close(); return pid

    def img_bytes(pm):
        if pm is None or pm.isNull(): return None
        im = pm.toImage(); return bytes(im.constBits().asarray(im.sizeInBytes()))

    try:
        # --- 1. каждый QAction ---
        db = tmp / "all.db"; PID = make_db(db)
        w = MainWindow(BackendAPI(db)); w.show(); spin(150)
        places = dict(w.ribbon.places)
        # разрушающие действия (убирают запись/БД) — в конец прохода, как в reports/qa/e2e_click_all.py
        acts = [a for a in places if a.objectName() not in LATE + ("act_exit",)] + [a for n in LATE for a in places if a.objectName() == n]
        extra = [a for a in w.findChildren(QAction) if a.objectName().startswith("act_align_")]
        skipped = []
        for a in acts + extra:
            tab = places.get(a, ("Рисование", ""))[0]
            try:
                w.ribbon.select(tab); spin(30)
                if tab == "База данных":
                    if a.objectName() not in ("act_display_printed", "act_display_unprinted"):
                        (w.findChild(QAction, "act_display_all") or QAction()).trigger(); spin(30)
                    if a.objectName() not in ("act_filter_apply", "act_filter_reset"): w._select_person(PID)
                else:
                    le = w.layout_editor; items = [i for i in le.scene.items() if i.flags() & i.GraphicsItemFlag.ItemIsSelectable]
                    if items and a.objectName() != "act_paste": le.scene.clearSelection(); items[0].setSelected(True)
                spin(30)
                if not a.isEnabled(): skipped.append(a.objectName()); continue
                n = len(EXC); OPENED.clear(); a.trigger(); spin(250)
                if a.isCheckable() and a.objectName() not in ("act_display_all", "act_display_printed", "act_display_unprinted"): a.trigger(); spin(80)
                chk(f"ACT {a.objectName()} «{a.text()}»", len(EXC) == n, EXC[-1] if len(EXC) > n else f"диалоги: {OPENED or '—'}")
            except Exception:  # noqa: BLE001
                chk(f"ACT {a.objectName()}", False, traceback.format_exc()[-600:])
        chk("Все действия ленты доступны в подготовленном состоянии", not skipped, skipped or "все нажаты")
        w.close()
        # --- 2. диалоги напрямую ---
        w2 = MainWindow(BackendAPI(db)); w2.show(); spin(100)
        for name, title in (("act_settings", "Настройки"), ("act_field_manager", "Настр. поля"), ("act_card_add", "Карта: добавить"),
                            ("act_card_edit", "Карта: изменить"), ("act_import", "Импорт"), ("act_export", "Экспорт"),
                            ("act_position", "Положение"), ("act_queue", "Очередь печати"), ("act_about", "О программе")):
            a = w2.findChild(QAction, name)
            if a is None: chk(f"DLG {title}", False, f"нет {name}"); continue
            w2.ribbon.select(dict(w2.ribbon.places).get(a, ("Главная",))[0]); spin(30)
            if name.startswith("act_card") or name == "act_queue": w2._select_person(PID)
            else:
                le = w2.layout_editor; its = [i for i in le.scene.items() if i.flags() & i.GraphicsItemFlag.ItemIsSelectable]
                if its: le.scene.clearSelection(); its[0].setSelected(True)
            spin(30); OPENED.clear(); n = len(EXC); a.trigger(); spin(400)
            chk(f"DLG {title} открылся и закрылся без исключений", OPENED and len(EXC) == n,
                EXC[-1] if len(EXC) > n else OPENED or "диалог не открылся")
        # камера (блок фото формы записи, D22) и менеджер полей — открываются даже без камеры
        from .record_form import RecordForm
        n = len(EXC); f = RecordForm(w2.api, None, w2); f.show(); QApplication.processEvents(); vis = f.isVisible(); spin(150)
        pb = f.photo_block
        chk("DLG Камера (блок «Фото» формы записи) открылся", vis and (pb.has_camera or (pb.status.text() and not pb.b_shot.isEnabled())) and len(EXC) == n,
            f"камера={'есть' if pb.has_camera else 'нет'}; надпись: {pb.status.text()!r}")
        pb.stop(); f.reject(); spin(30)
        n = len(EXC); fm = w2.field_manager(exec_=False); fm.show(); QApplication.processEvents(); vis = fm.isVisible(); spin(80)
        cols = [fm.tree.headerItem().text(i) for i in range(fm.tree.columnCount())]
        chk("DLG Менеджер полей открылся (Поле | Тип данных | Значение по умолчанию)",
            vis and cols == ["Поле", "Тип данных", "Значение по умолчанию"] and fm.tree.topLevelItemCount() > 0 and len(EXC) == n, cols)
        fm.reject(); spin(30)
        w2.close()
        # --- 3. добавить запись → текст на превью ---
        for tag, wf in (("поля_есть", True), ("без_person_fields", False)):
            try:
                d = tmp / f"add_{tag}.db"; make_db(d, wf)
                w = MainWindow(BackendAPI(d)); w.show(); spin(100); w.ribbon.select("База данных"); spin(50)
                w.records.select_id(None); w.records.view.clearSelection(); spin(50)
                pp = w.preview_panel; empty = img_bytes(pp.pixmaps.get("front"))
                vals = {"last_name": "Щёголева", "first_name": "Юлия", "faculty": "Химфак «Ё»"}
                shot = QImage(320, 400, QImage.Format.Format_RGB32); shot.fill(QColor("#3A7BD5"))
                FILL.update(vals); FILL["__photo__"] = shot; CAM.clear(); w.act_card_add.trigger(); spin(600)
                new = [p for p in w.api.list_persons() if p["fields"].get("last_name") == "Щёголева"]
                chk(f"ADD[{tag}] запись сохранена", new and all(new[0]["fields"].get(k) == v for k, v in vals.items()), new[0]["fields"] if new else "нет записи")
                import os
                ph = (new[0].get("photo_path") or "") if new else ""
                chk(f"ADD[{tag}] фото с камеры (внутри «Добавить карту» → блок «Фото») сохранено в photos/, путь относительный",
                    ph.startswith("photos/") and os.path.isfile(os.path.join(w.api.base_dir, ph)),
                    f"photo_path={ph!r}; камера={'есть' if CAM and CAM[0] else 'нет — снимок подан в тот же слот imageCaptured'}")
                spin(300); after = img_bytes(pp.pixmaps.get("front"))
                diff = None if (empty is None or after is None) else sum(x != y for x, y in zip(empty, after))
                chk(f"ADD[{tag}] текст на превью (отличается от пустого шаблона)", after is not None and (empty is None or diff > 200), f"diff_bytes={diff}")
                t = pp.fields; shown = [t.item(r, 1).text() if t.item(r, 1) else "" for r in range(t.rowCount())]
                chk(f"ADD[{tag}] «Поле шаблона | Значение из БД» показывает значения", all(v in shown for v in vals.values()), shown)
                w.close(); spin(50)
            except Exception:  # noqa: BLE001
                chk(f"ADD[{tag}] сценарий без исключений", False, traceback.format_exc()[-800:])
    finally:
        tm.stop()
    spin(200)
    left = [f"{type(x).__name__}«{x.windowTitle()}»" for x in QApplication.topLevelWidgets() if isinstance(x, QDialog) and x.isVisible()]
    chk("После сценария нет открытых модальных окон", QApplication.activeModalWidget() is None and not left, left or "нет")
    for x in QApplication.topLevelWidgets(): x.close()
