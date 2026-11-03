"""QA этап 14: редактор фото «Редактировать изображение» (offscreen).
QT_QPA_PLATFORM=offscreen .venv/bin/python reports/qa/e2e_stage14.py  [--shots] (скриншоты в reports/qa/stage14_*.png)"""
import os, sys, json, tempfile, pathlib, re, shutil, hashlib, sqlite3
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen"); sys.dont_write_bytecode = True
ROOT = pathlib.Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))
from PIL import Image, ImageStat
import numpy as np, cv2
from PyQt6.QtWidgets import QApplication, QPushButton
from PyQt6.QtGui import QAction, QImage
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtTest import QTest
app = QApplication.instance() or QApplication(sys.argv)
from ui.backend_api import BackendAPI
from ui import photo_editor as pe, photo_block as pb
from ui.record_form import RecordForm
from badge_backend import api as bapi, db as bdb
from badge_backend.services import photo_edit as bpe
TMP = pathlib.Path(tempfile.mkdtemp(prefix="bgqa14_")); RES = []
def chk(n, ok, ev=""): RES.append((n, bool(ok), str(ev)[:300])); print("PASS" if ok else "FAIL", "|", n, "|", str(ev)[:300])
md5 = lambda p: hashlib.md5(pathlib.Path(p).read_bytes()).hexdigest()
FACE = ROOT / "tests/fixtures/face_astronaut.jpg"
SRC = TMP / "src"; SRC.mkdir(); shutil.copy(FACE, SRC / "face.jpg"); FACEP = SRC / "face.jpg"
Image.new("RGB", (300, 400), (150, 150, 150)).save(SRC / "noface.png")
ASPECT = 320 / 400
api = BackendAPI(TMP / "p.db", TMP)
api.upsert_field("last_name", "Фамилия", 0, data_type="text"); api.upsert_field("foto", "Фото", 1, data_type="image")
api.create_element(type="photo", x=10, y=10, w=320, h=400, field_name="foto")
(TMP / "photos").mkdir(exist_ok=True); shutil.copy(FACE, TMP / "photos/orig.jpg")
pid = api.create_person({"last_name": "Гагарин", "foto": "photos/orig.jpg"})
opened = []
def hook(d): opened.append(d); return 0
pe.editor_hook = hook

# ---- открытие: один QAction, двойной клик и контекстное меню; без авто-открытия ----
f = RecordForm(api, pid); f.show(); app.processEvents()
blk = f.image_edits["foto"]
acts = [a for a in blk.findChildren(QAction) if a.objectName() == "act_photo_edit"]
chk("Открытие: в блоке фото ровно один QAction act_photo_edit", len(acts) == 1, [a.text() for a in acts])
chk("Открытие: тот же QAction в контекстном меню фото", blk.still.contextMenuPolicy() == Qt.ContextMenuPolicy.ActionsContextMenu and acts and acts[0] in blk.still.actions())
QTest.mouseDClick(blk.still, Qt.MouseButton.LeftButton); app.processEvents()
chk("Открытие: двойной клик по фото → «Редактировать изображение»", opened and opened[-1].windowTitle() == "Редактировать изображение", [d.windowTitle() for d in opened])
n0 = len(opened); acts[0].trigger(); app.processEvents()
chk("Открытие: контекстное меню (тот же QAction) → редактор", len(opened) == n0 + 1)
chk("Открытие: рамка с пропорциями фото-элемента (320×400)", abs(opened[-1].aspect - ASPECT) < 1e-6, opened[-1].aspect)
f.reject()
nf = RecordForm(api); nf.show(); app.processEvents(); n0 = len(opened)
nf.photo_block.from_file(str(FACEP)); app.processEvents()
qi = QImage(str(FACEP)); nf.photo_block.set_captured(qi); app.processEvents()
chk("Нет авто-открытия после загрузки файла и снимка с камеры", len(opened) == n0, len(opened) - n0)
nf.photo_block.from_file(str(FACEP)); QTest.mouseDClick(nf.photo_block.still, Qt.MouseButton.LeftButton); app.processEvents()
chk("Открытие из диалога создания записи (двойной клик)", len(opened) == n0 + 1)
nf.reject()
cnt = {}
for p in (ROOT / "ui").glob("*.py"):
    s = p.read_text(encoding="utf-8")
    if p.name not in ("smoke_test.py", "qa_click_all.py", "self_test.py"):
        cnt[p.name] = len(re.findall(r"PhotoEditor\(", s)) - len(re.findall(r"class PhotoEditor\(", s))
chk("Дубли: PhotoEditor создаётся только в одном обработчике (photo_block.edit_photo)", sum(cnt.values()) == 1 and cnt.get("photo_block.py") == 1, {k: v for k, v in cnt.items() if v})
mk = sum(len(re.findall(r"make_edit_action\(", p.read_text(encoding="utf-8"))) for p in (ROOT / "ui").glob("*.py") if p.name not in ("smoke_test.py", "qa_click_all.py"))
chk("Дубли: QAction «Редактировать изображение» создаётся одной фабрикой (def + 1 вызов)", mk == 2, mk)

# ---- ползунки ----
d = pe.PhotoEditor(str(FACEP), api, ASPECT); d.resize(700, 860); d.show(); app.processEvents()
rng = {k: (d.sl[k].minimum(), d.sl[k].maximum(), d.sp[k].minimum(), d.sp[k].maximum()) for k in d.sl}
exp = {"brightness": (-50, 50), "contrast": (-50, 50), "scale": (10, 400), "rotate": (-180, 180)}
chk("Ползунки + поле ввода: диапазоны", all(rng[k] == (*v, *v) for k, v in exp.items()), rng)
chk("Ползунки: начальные 0/0/100/0", [d.sp[k].value() for k in ("brightness", "contrast", "scale", "rotate")] == [0, 0, 100, 0])
d.sl["brightness"].setValue(30); chk("Ползунок ↔ поле синхронны", d.sp["brightness"].value() == 30)
before = d.pix.pixmap().toImage(); QTest.qWait(150); app.processEvents(); after = d.pix.pixmap().toImage()
ref = bapi.apply_photo_edit(d.src, d.params(crop=False))
chk("Превью перерисовывается сразу (≤150 мс) и = Backend apply_photo_edit", before != after and d.img.tobytes() == ref.tobytes(), d.params(crop=False))
d.sp["brightness"].setValue(0); d.sp["rotate"].setValue(90); QTest.qWait(150)
chk("Вращать 90° меняет размер превью", d.img.size == (d.src.height, d.src.width) or d.img.size != d.src.size, (d.src.size, d.img.size))
d.sp["rotate"].setValue(0); d.sp["scale"].setValue(50); QTest.qWait(150)
chk("Масштаб 50 % → превью вдвое меньше", abs(d.img.width - d.src.width / 2) <= 1, (d.src.size, d.img.size)); d.sp["scale"].setValue(100); QTest.qWait(150)
bad = []
for p in (ROOT / "ui").glob("*.py"):
    for i, l in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if re.search(r"ImageEnhance|ImageOps|ImageFilter|\bcv2\b|import numpy|\bImage\.(?!open\b)\w+\(|img\.(rotate|resize|transpose|crop)\(|autocontrast|exif_transpose", l) and not l.lstrip().startswith("#"):
            bad.append(f"{p.name}:{i}")
chk("В ui/ нет обработки изображений (ImageEnhance/ImageOps/cv2/rotate/resize)", not bad, bad)

# ---- рамка ----
fr = d.frame; r = fr.rect()
chk("Рамка пунктирная", fr.pen().style() in (Qt.PenStyle.DashLine, Qt.PenStyle.DotLine, Qt.PenStyle.CustomDashLine), fr.pen().style())
chk("Рамка: пропорции = фото-элемент", abs(r.width() / r.height() - ASPECT) < 0.01, (r.width(), r.height()))
fr.move_by(QPointF(-20, -15), r); r2 = fr.rect()
chk("Рамка перетаскивается, размер тот же", (r2.x(), r2.y()) != (r.x(), r.y()) and abs(r2.width() - r.width()) < 1e-6, (r.x(), r.y(), r2.x(), r2.y()))
fr.resize_corner("br", QPointF(r2.right() - 40, r2.bottom() - 10), r2); r3 = fr.rect()
chk("Угол: размер меняется с сохранением пропорций", abs(r3.width() - r2.width()) > 1 and abs(r3.width() / r3.height() - ASPECT) < 0.01, (r3.width(), r3.height()))
fr.resize_corner("tl", QPointF(-1000, -1000), r3); r4 = fr.rect()
chk("Рамка не выходит за изображение, пропорции сохраняются", fr.bounds.contains(r4) and abs(r4.width() / r4.height() - ASPECT) < 0.01, (r4.x(), r4.y(), r4.width(), r4.height()))
d.reset_frame()
if "--shots" in sys.argv: app.processEvents(); d.grab().save(str(ROOT / "reports/qa/stage14_raw.png"))

# ---- Портрет ----
g = np.asarray(d.img.convert("L")); faces = cv2.CascadeClassifier(bpe.cascade_path()).detectMultiScale(g, 1.1, 5)
fx, fy, fw, fh = max(faces, key=lambda t: t[2] * t[3]) if len(faces) else (0, 0, 0, 0)
d.portrait.setChecked(True); app.processEvents(); x, y, w, h = d.crop()
chk("Портрет: лицо найдено, рамка поставлена", d.portrait.isChecked() and (x, y, w, h) != (0, 0, 0, 0) and "не найдено" not in d.status.text(), (x, y, w, h, d.status.text()))
chk("Портрет: лицо по центру по горизонтали (±5 %)", abs((x + w / 2) - (fx + fw / 2)) <= 0.05 * w, (x + w / 2, fx + fw / 2))
chk("Портрет: лицо ≈60–70 % высоты рамки", 0.58 <= fh / h <= 0.72, round(fh / h, 3))
chk("Портрет: запас над головой (≥ 0.25·высоты лица над рамкой Haar — волосы не срезаются)", fy - y >= 0.25 * fh, (fy - y, fh))
chk("Портрет: пропорции рамки сохранены", abs(w / h - ASPECT) < 0.01, w / h)
if "--shots" in sys.argv: app.processEvents(); d.grab().save(str(ROOT / "reports/qa/stage14_portrait.png"))
dn = pe.PhotoEditor(str(SRC / "noface.png"), api, ASPECT); c0 = dn.crop(); dn.portrait.setChecked(True); app.processEvents()
chk("Портрет без лица: рамка не меняется, статус «Лицо не найдено»", dn.crop() == c0 and dn.status.text().startswith("Лицо не найдено"), (c0, dn.crop(), dn.status.text()))
dn.done(0)

# ---- Автоэффект ----
low = Image.fromarray((np.asarray(Image.open(FACEP).convert("RGB")) * 0.3 + 20).astype("uint8")); low.save(SRC / "low.png")
da = pe.PhotoEditor(str(SRC / "low.png"), api, ASPECT); m0 = ImageStat.Stat(da.img.convert("L")).mean[0]
da.autoeffect.setChecked(True); QTest.qWait(150); m1 = ImageStat.Stat(da.img.convert("L")).mean[0]
ex = da.img.convert("L").getextrema()
chk("Автоэффект: средняя яркость нормализована к ~128, контраст растянут", abs(m1 - 128) < abs(m0 - 128) and abs(m1 - 128) < 30 and ex[1] - ex[0] > 200, (round(m0), round(m1), ex))
ae = da.img.tobytes(); da.sp["brightness"].setValue(20); QTest.qWait(150)
chk("Автоэффект: ручные ползунки применяются поверх", da.img.tobytes() != ae and ImageStat.Stat(da.img.convert("L")).mean[0] > m1)
src_ = inspect_src = pathlib.Path(bpe.__file__).read_text(encoding="utf-8")
chk("Автоэффект: Backend autocontrast(cutoff=1) + нормализация средней", "autocontrast(im, cutoff=1)" in src_ and "128.0 / mean" in src_)
da.done(0)
d.portrait.setChecked(False); d.autoeffect.setChecked(True); QTest.qWait(150)
if "--shots" in sys.argv: app.processEvents(); d.grab().save(str(ROOT / "reports/qa/stage14_autoeffect.png"))
d.autoeffect.setChecked(False)

# ---- По умолчанию ----
fresh = BackendAPI(TMP / "fresh.db", TMP); df = pe.PhotoEditor(str(FACEP), fresh, ASPECT)
chk("«По умолчанию» без сохранённых → 0/0/100/0, без галочек", [df.sp[k].value() for k in ("brightness", "contrast", "scale", "rotate")] == [0, 0, 100, 0] and not df.autoeffect.isChecked())
df.sp["brightness"].setValue(12); df.sp["contrast"].setValue(-7); df.sp["scale"].setValue(150); df.sp["rotate"].setValue(5)
df.autoeffect.setChecked(True); df.portrait.setChecked(True); df.save_defaults()
row = sqlite3.connect(TMP / "fresh.db").execute("SELECT value FROM project_settings").fetchall()
chk("«Установить по умолчанию» → project_settings", row and json.loads(row[0][0]).get("brightness") == 12, row)
df.sp["brightness"].setValue(0); df.autoeffect.setChecked(False); df.load_defaults()
chk("«По умолчанию» возвращает сохранённые параметры", [df.sp[k].value() for k in ("brightness", "contrast", "scale", "rotate")] == [12, -7, 150, 5] and df.autoeffect.isChecked())
df.done(0); df2 = pe.PhotoEditor(str(FACEP), fresh, ASPECT)
chk("Новый редактор открывается с умолчаниями проекта", df2.sp["scale"].value() == 150)
chk("Галочка «Портрет» сохраняется в умолчаниях (ТЗ: «параметры и галочки»)", "portrait" in json.loads(row[0][0]) and df2.portrait.isChecked(), json.loads(row[0][0]))
df2.done(0); fresh.close()

# ---- кнопки ----
btn = [b.text() for b in d.findChildren(QPushButton)]
chk("Нижний ряд только «Применить» и «Отмена», нет «УгЧ»", "Применить" in btn and "Отмена" in btn and not any("УгЧ" in t for t in btn), btn)

# ---- Применить / Отмена ----
d.done(0); pe.editor_hook = lambda dlg: (dlg.sp.__getitem__("brightness").setValue(15), dlg.apply())[1]
h0 = md5(TMP / "photos/orig.jpg"); files0 = set(os.listdir(TMP / "photos"))
f = RecordForm(api, pid); f.show(); blk = f.image_edits["foto"]; blk.edit_photo(); app.processEvents()
db_mid = api.get_person(pid)["fields"]["foto"]
chk("Применить: в БД до «Сохранить» ничего не пишется", db_mid == "photos/orig.jpg", db_mid)
chk("Применить: путь нового фото в форме", blk.path.startswith("photos/") and blk.path != "photos/orig.jpg", blk.path)
f.save(); app.processEvents(); newp = api.get_person(pid)["fields"]["foto"]
chk("Применить+Сохранить: путь в поле image, файл существует", newp == blk.path and (TMP / newp).is_file(), newp)
chk("Исходник не перезаписан", md5(TMP / "photos/orig.jpg") == h0)
f = RecordForm(api, pid); f.show(); f.image_edits["foto"].edit_photo(); app.processEvents(); f.reject()
chk("Применить + «Отмена» формы: запись не меняется", api.get_person(pid)["fields"]["foto"] == newp)
orphans = set(os.listdir(TMP / "photos")) - files0 - {pathlib.Path(newp).name}
print("НАБЛЮДЕНИЕ | файлы-сироты в photos/ после «Отмена» формы:", sorted(orphans))
pe.editor_hook = lambda dlg: (dlg.reject(), 0)[1]; files1 = set(os.listdir(TMP / "photos"))
f = RecordForm(api, pid); f.show(); f.image_edits["foto"].edit_photo(); f.save()
chk("«Отмена» редактора: без изменений и без новых файлов", api.get_person(pid)["fields"]["foto"] == newp and set(os.listdir(TMP / "photos")) == files1)

# ---- EXIF ----
im = Image.open(FACEP).convert("RGB").transpose(Image.Transpose.ROTATE_90)   # «сырой» снимок, ориентация 6 → поворот при показе
ex_ = Image.Exif(); ex_[0x0112] = 6; im.save(SRC / "exif.jpg", exif=ex_, quality=95)
de = pe.PhotoEditor(str(SRC / "exif.jpg"), api, ASPECT); de.show(); app.processEvents()
tr = bapi.load_photo_for_edit(str(SRC / "exif.jpg"))
chk("EXIF: превью открыто с учётом ориентации (load_photo_for_edit)", de.src.size == tr.size and de.src.size == Image.open(FACEP).size, (de.src.size, tr.size))
de.portrait.setChecked(True); app.processEvents(); crop = de.crop(); prm = de.params()
rel = api.apply_and_save_photo(str(SRC / "exif.jpg"), prm); out = Image.open(TMP / rel).convert("RGB")
exp_ = bapi.apply_photo_edit(tr, prm).convert("RGB")
diff = np.abs(np.asarray(out, dtype=int) - np.asarray(exp_, dtype=int)).mean() if out.size == exp_.size else 999
chk("EXIF: сохранённый кадр = рамка превью (размер и содержимое)", out.size == (crop[2], crop[3]) and diff < 6, (out.size, crop, round(float(diff), 2)))
de.done(0)

# ---- зависимости, spec, CI, миграция ----
req = (ROOT / "requirements.txt").read_text(); spec = (ROOT / "packaging/badge_generator.spec").read_text(); ci = (ROOT / ".github/workflows/build-windows.yml").read_text()
chk("requirements: opencv-python-headless>=4.8,<5", re.search(r"^opencv-python-headless>=4\.8,<5", req, re.M))
chk("spec: haarcascade_frontalface_default.xml в datas + манифест", "haarcascade_frontalface_default.xml" in spec and "MISSING" in spec)
chk("CI: манифест проверяется на MISSING", 'like "MISSING*"' in ci)
chk("Каскад найден локально (cascade_path)", pathlib.Path(bpe.cascade_path()).is_file(), bpe.cascade_path())
old = TMP / "old.db"; c = bapi.connect(str(old)); bapi.upsert_field(c, "last_name", "Фамилия", 0); bapi.create_person(c, {"last_name": "Old"})
c.execute("DROP TABLE project_settings"); c.execute("PRAGMA user_version=5"); c.commit(); c.close()
c = bapi.connect(str(old)); v = c.execute("PRAGMA user_version").fetchone()[0]
t = c.execute("SELECT name FROM sqlite_master WHERE name='project_settings'").fetchone(); n = c.execute("SELECT COUNT(*) FROM persons").fetchone()[0]
chk("Миграция v5→v6: project_settings создана, данные целы", v == bdb.LATEST == 6 and t and n == 1, (v, t, n)); c.close()
tests = (ROOT / "tests/test_photo_edit.py").read_text(encoding="utf-8")
chk("Тесты Backend: параметры, портрет с лицом и без, автоэффект", all(re.search(k, tests, re.I) for k in ("brightness|contrast", "face", "no.?face|без лиц|None", "autoeffect")))

api.close(); n_ok = sum(r[1] for r in RES)
(TMP / "e2e_stage14_results.json").write_text(json.dumps(RES, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"ИТОГО: {n_ok}/{len(RES)} PASS; tmp={TMP}"); sys.exit(0 if n_ok == len(RES) else 1)
