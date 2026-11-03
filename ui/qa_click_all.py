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
        # этап 13: экспорт данных (D34) и импорт (D31–D33, D35) на API Backend
        keys = [fm.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) for i in range(fm.tree.topLevelItemCount())]
        chk("Менеджер полей: фото — поле типа image (нет постоянной строки «Фото», вариант а)",
            all(k_ and k_[0] == "field" for k_ in keys) and "photo" in fm.LINKABLE, keys)
        tm.stop()   # авто-закрыватель не должен закрывать проверяемые диалоги
        try:
            from . import dialogs as dlg
            n = len(EXC); xl = tmp / "qa13.xlsx"; dbo = tmp / "qa13.db"
            ed = dlg.ExportDialog(w2.api, [], w2, filtered_ids=[PID]); ed.m_data.setChecked(True); ed.show(); spin(50)
            fm_ok = [ed.data_fmt.itemData(i) for i in range(ed.data_fmt.count())] == ["xlsx", "xls", "csv", "db"]
            hint_xlsx = not ed.hint.isHidden(); ed.d_filtered.setChecked(True); ed.target.setText(str(xl)); r1 = ed.start()
            ed.data_fmt.setCurrentIndex(3); hint_db = not ed.hint.isHidden(); ed.d_all.setChecked(True); ed.target.setText(str(dbo)); r2 = ed.start()
            ed.close()
            chk("DLG Экспорт данных: xlsx/xls/csv/db, отфильтрованные, подсказка D29 (не для .db)",
                fm_ok and r1 and r2 and xl.exists() and dbo.exists() and hint_xlsx and not hint_db and len(EXC) == n,
                f"xlsx={r1} db={r2} hint xlsx/db={hint_xlsx}/{hint_db}; {ed.status.text()[:120]}")
            n = len(EXC); di = dlg.ImportDialog(w2.api, w2); di.set_file(str(xl)); di.show(); spin(50)
            cols = [di.table.horizontalHeaderItem(i).text() for i in range(4)]
            okb = di._save_binding(path=str(tmp / "qa13.json")) is not None and di._load_binding(path=str(tmp / "qa13.json"))
            before = len(w2.api.list_persons()); di.run(); added = di.report.added if di.report else None
            di.reject(); spin(30)
            chk("DLG Импорт xlsx: «Поле БД | Тип | Сопоставлено | Колонка файла ▾», привязка, превью, импорт, sheet.close()",
                cols == ["Поле БД", "Тип", "Сопоставлено", "Колонка файла ▾"] and okb and added == 1 and di.sheets == []
                and len(w2.api.list_persons()) == before + 1 and di.preview.rowCount() == 1 and len(EXC) == n, f"{cols}; added={added}")
            n = len(EXC); api3 = BackendAPI(str(tmp / "qa13_fresh.db"), base_dir=str(tmp)); dd = dlg.ImportDialog(api3, w2)
            dd.set_file(str(dbo)); asked = []
            dlg.confirm_fields_hook = lambda new: asked.append(new) or True; dd.run(); dlg.confirm_fields_hook = None
            got = dd.report.added if dd.report else None; nf = len(api3.list_fields()); dd.reject(); api3.close()
            chk("DLG Импорт .db: подтверждение → import_fields=True, поля созданы", bool(asked) and nf > 0 and got and len(EXC) == n,
                f"новые поля={asked[:1]}; создано полей={nf}; добавлено={got}")
            # этап 14: редактор фото — поле image, двойной клик по фото формы записи (тот же QAction, что в контекстном меню)
            from . import photo_editor as pe
            from . import backend_api as ba
            from PyQt6.QtTest import QTest
            import shutil
            from pathlib import Path
            n = len(EXC); a14 = BackendAPI(str(tmp / "qa14.db"), base_dir=str(tmp)); a14.upsert_field("foto", "Фото", 0, data_type="image")
            el = a14.create_element(type="photo", x=0, y=0, w=300, h=400); a14.link_field(el, "foto")
            real_t = ba._backend_fn("photo_edit_target") is not None; real_d = ba._backend_fn("PhotoSession") is not None
            if not real_t:    # пока нет в Backend — подмена только на тестовом экземпляре
                a14.photo_edit_target = lambda fn: {"aspect": 0.75, "size": (300, 400), "element_id": el} if fn == "foto" else None
            face = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "face_astronaut.jpg"
            ph = tmp / "qa14.png"
            if face.is_file(): ph = tmp / "qa14.jpg"; shutil.copy(face, ph)
            else: img = QImage(240, 320, QImage.Format.Format_RGB32); img.fill(QColor("#7A8F9C")); img.save(str(ph))
            f = RecordForm(a14, None, w2); f.show(); spin(50); pb = f.edits["foto"]; pb.from_file(str(ph)); spin(30)
            auto = pb.editor is not None; seen = []; res = {}
            def _drive(d):
                d.show(); spin(50); seen.append((d.windowTitle(), d.isVisible(), d.b_apply.text(), d.b_cancel.text()))
                px0 = d.img.tobytes(); d.sl["brightness"].setValue(25); d.sl["contrast"].setValue(10); d.update_preview(); spin(20)
                res["preview"] = d.img.tobytes() != px0
                d.portrait.setChecked(True); spin(20)
                res["aspect"] = (d.aspect, a14.photo_edit_target("foto")["aspect"])
                fr = d.frame.rect(); res["portrait"] = (d.portrait.isChecked() and abs(fr.width() / fr.height() - d.aspect) < 0.02) \
                    or "Лицо не найдено" in d.status.text()
                d.autoeffect.setChecked(True); spin(100); res["auto"] = d.params()["autoeffect"] is True
                from PyQt6.QtCore import QRectF, QPointF
                vp = QRectF(d.view.viewport().rect()); ok42 = []
                for mv in (None, QPointF(-10000, -10000), QPointF(10000, 10000)):
                    if mv is not None: d.frame.move_by(mv); spin(20)
                    ok42.append(vp.contains(d.frame.visible_device_rect()))
                res["frame4"] = all(ok42); d.portrait.setChecked(False); d.portrait.setChecked(True); spin(20)
                # D41 проверяет сохранение галочки, а не поиск лица (после яркости/автоэффекта лицо может не найтись)
                d.portrait.blockSignals(True); d.portrait.setChecked(True); d.portrait.blockSignals(False)
                saved = d.save_defaults(); d.sl["brightness"].setValue(-30); d.autoeffect.setChecked(False)
                d.portrait.setChecked(False); d.load_defaults(); res["sent_portrait"] = bool(saved) and "portrait" in saved
                res["portrait_restored"] = d.portrait.isChecked() or "Лицо не найдено" in d.status.text()   # нет лица → галочка снимается
                d3 = pe.PhotoEditor(str(ph), a14, None, field_name="foto")
                box = ba.detect_face_crop(d3.img, d3.aspect)
                res["portrait_reopen"] = a14.get_photo_edit_defaults().get("portrait") is True and (
                    (d3.portrait.isChecked() and d3.crop() == tuple(box)) if box else "Лицо не найдено" in d3.status.text())
                d3.reject()
                a14.set_photo_edit_defaults({**a14.get_photo_edit_defaults(), "portrait": False})
                res["defaults"] = bool(saved) and d.sp["brightness"].value() == 25 and d.autoeffect.isChecked() \
                    and a14.get_photo_edit_defaults()["brightness"] == 25
                res["apply"] = d.apply(); res["path"] = d.result_path; res["status"] = d.status.text()
                if d.isVisible(): d.reject()
            pe.editor_hook = _drive
            try: QTest.mouseDClick(pb.still, Qt.MouseButton.LeftButton); spin(50)
            finally: pe.editor_hook = None
            val = pb.text(); fv = val if f.save() is not False else None; spin(30); pb.stop()
            # существующая запись: «Применить», затем «Отмена» формы → значение поля в БД не меняется
            pid = a14.list_persons()[-1]["id"]; db0 = a14.get_person(pid)["fields"].get("foto"); r2 = {}
            f2 = RecordForm(a14, pid, w2); f2.show(); spin(30); pb2 = f2.edits["foto"]
            pe.editor_hook = lambda d: (r2.update(ok=d.apply(), path=d.result_path), d.isVisible() and d.reject())
            try: QTest.mouseDClick(pb2.still, Qt.MouseButton.LeftButton); spin(50)
            finally: pe.editor_hook = None
            mid = a14.get_person(pid)["fields"].get("foto"); form2 = pb2.text(); pb2.stop(); f2.reject(); spin(30)
            db1 = a14.get_person(pid)["fields"].get("foto"); p2 = r2.get("path")
            gone = p2 is not None and not (tmp / p2).is_file(); disc = getattr(f2, "discarded", None); a14.close()
            chk("DLG «Редактировать изображение» по двойному клику на фото формы записи (не открывается сам после файла)",
                not auto and seen and seen[0][:2] == ("Редактировать изображение", True) and pb.act_edit in pb.still.actions() and len(EXC) == n,
                seen or "не открылся")
            if ba.photo_edit_available():
                chk("DLG Редактор фото: ползунки меняют превью (Backend apply_photo_edit)", res.get("preview"), res)
                chk("DLG Редактор фото: «Портрет» ставит рамку по лицу или статус «Лицо не найдено»", res.get("portrait"), res.get("status"))
                chk("DLG Редактор фото: «Автоэффект» в параметрах", res.get("auto"), res)
                chk("DLG Редактор фото D42: рамка с пером целиком видна (центр и края изображения)", res.get("frame4"), res)
                if "portrait" in ba.PHOTO_EDIT_DEFAULTS:     # D41: Backend хранит ключ portrait
                    chk("DLG Редактор фото D41: «Портрет» сохраняется в умолчаниях, восстанавливается и при открытии ставит рамку по лицу",
                        res.get("sent_portrait") and res.get("portrait_restored") and res.get("portrait_reopen"), res)
                chk("DLG Редактор фото: пропорции рамки = Backend photo_edit_target (поле image)", res.get("aspect") and res["aspect"][0] == res["aspect"][1], res.get("aspect"))
                if real_d:
                    chk("DLG Редактор фото D43: «Отмена» формы → PhotoSession.discard() удаляет файл редактора без ссылок",
                        disc == [p2] and gone and db1 == db0 and (tmp / db0).is_file(), (disc, p2, gone))
                chk("DLG Редактор фото: умолчания проекта сохраняются и восстанавливаются (Backend)", res.get("defaults"), res)
                chk("DLG Редактор фото: «Применить» → новый photos/… в поле image", res.get("apply") is True and str(res.get("path", "")).startswith("photos/")
                    and val == res["path"] and (tmp / val).is_file() and ph.is_file() and db0 == fv, res)
                chk("DLG Редактор фото: «Применить» + «Отмена» формы существующей записи — значение в БД не меняется",
                    r2.get("ok") is True and form2 == r2.get("path") != db0 and mid == db0 == db1, {**r2, "db0": db0, "db1": db1})
        except Exception:  # noqa: BLE001
            chk("DLG Импорт/экспорт этапа 13 без исключений", False, traceback.format_exc()[-800:])
        finally:
            tm.start()
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
