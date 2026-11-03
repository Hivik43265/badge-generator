"""QA этап 14 (перепроверка): редактор фото «Редактировать изображение», offscreen.
QT_QPA_PLATFORM=offscreen .venv/bin/python reports/qa/e2e_stage14.py [--shots]  → reports/qa/stage14_{raw,portrait,autoeffect,card}.png"""
import os, sys, json, tempfile, pathlib, re, shutil, hashlib, sqlite3
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen"); sys.dont_write_bytecode = True
ROOT = pathlib.Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))
from PIL import Image, ImageStat
import numpy as np, cv2
from PyQt6.QtWidgets import QApplication, QPushButton
from PyQt6.QtGui import QAction, QImage, QColor
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtTest import QTest
app = QApplication.instance() or QApplication(sys.argv)
from ui.backend_api import BackendAPI
from ui import photo_editor as pe, photo_block as pb
from ui.record_form import RecordForm
from badge_backend import api as bapi, db as bdb
from badge_backend.services import photo_edit as bpe
SHOTS = "--shots" in sys.argv; QA = ROOT / "reports/qa"
TMP = pathlib.Path(tempfile.mkdtemp(prefix="bgqa14_")); RES = []
def chk(n, ok, ev=""): RES.append((n, bool(ok), str(ev)[:300])); print("PASS" if ok else "FAIL", "|", n, "|", str(ev)[:300])
md5 = lambda p: hashlib.md5(pathlib.Path(p).read_bytes()).hexdigest()
FACE = ROOT / "tests/fixtures/portrait_biden.jpg"
SRC = TMP / "src"; SRC.mkdir(); shutil.copy(FACE, SRC / "face.jpg"); FACEP = SRC / "face.jpg"
Image.new("RGB", (300, 400), (150, 150, 150)).save(SRC / "noface.png")
def project(name, ew, eh, extra_free=False):
    a = BackendAPI(TMP / f"{name}.db", TMP / name); a.upsert_field("last_name", "Фамилия", 0, data_type="text")
    a.upsert_field("foto", "Фото", 1, data_type="image")
    a.create_element(type="photo", x=600, y=60, w=ew, h=eh, field_name="foto", side="front")
    a.create_element(type="field", x=40, y=60, w=500, h=80, field_name="last_name")
    if extra_free: a.upsert_field("foto2", "Фото 2", 2, data_type="image")
    (TMP / name / "photos").mkdir(parents=True, exist_ok=True); return a
api = project("p", 330, 413, extra_free=True)    # ≈ 28×35 мм
shutil.copy(FACE, TMP / "p/photos/orig.jpg")
pid = api.create_person({"last_name": "Байден", "foto": "photos/orig.jpg"})
TG = api.photo_edit_target("foto"); ASPECT = TG["aspect"]
opened = []; pe.editor_hook = lambda d: (opened.append(d), 0)[1]

# ---- открытие ----
f = RecordForm(api, pid); f.show(); app.processEvents(); blk = f.image_edits["foto"]
acts = [a for a in blk.findChildren(QAction) if a.objectName() == "act_photo_edit"]
chk("Открытие: один QAction act_photo_edit в блоке фото", len(acts) == 1, [a.text() for a in acts])
chk("Открытие: тот же QAction в контекстном меню", blk.still.contextMenuPolicy() == Qt.ContextMenuPolicy.ActionsContextMenu and acts[0] in blk.still.actions())
QTest.mouseDClick(blk.still, Qt.MouseButton.LeftButton); app.processEvents()
chk("Открытие: двойной клик → «Редактировать изображение»", opened and opened[-1].windowTitle() == "Редактировать изображение")
n0 = len(opened); acts[0].trigger(); app.processEvents(); chk("Открытие: контекстное меню → редактор", len(opened) == n0 + 1)
chk("Рамка формы: пропорции = photo_edit_target(foto)", opened[-1].aspect == ASPECT and opened[-1].field_name == "foto", (opened[-1].aspect, TG))
f.reject()
nf = RecordForm(api); nf.show(); n0 = len(opened)
nf.image_edits["foto"].from_file(str(FACEP)); nf.image_edits["foto"].set_captured(QImage(str(FACEP))); app.processEvents()
chk("Нет авто-открытия после файла и снимка", len(opened) == n0)
QTest.mouseDClick(nf.image_edits["foto"].still, Qt.MouseButton.LeftButton); app.processEvents()
chk("Открытие из формы создания (двойной клик)", len(opened) == n0 + 1); nf.reject()

# ---- пропорции из шаблона (мм, 300 DPI) ----
mm = lambda px: px * 25.4 / 300
chk("photo_edit_target: мм и px 300 DPI по элементу", abs(TG["width_mm"] - mm(330)) < 0.05 and abs(TG["height_mm"] - mm(413)) < 0.05 and TG["size"] == (330, 413), TG)
a2 = project("q", 400, 400); t2 = a2.photo_edit_target("foto")
d1 = pe.PhotoEditor(str(FACEP), api, None, field_name="foto"); d2 = pe.PhotoEditor(str(FACEP), a2, None, field_name="foto")
r1, r2 = d1.frame.rect(), d2.frame.rect()
chk("Два шаблона → разные пропорции рамки по мм", abs(r1.width() / r1.height() - 330 / 413) < 0.01 and abs(r2.width() / r2.height() - 1.0) < 0.01, (round(r1.width() / r1.height(), 3), round(r2.width() / r2.height(), 3), t2["width_mm"], t2["height_mm"]))
a2.create_element(type="photo", x=10, y=10, w=200, h=100, field_name="foto", side="back"); a2.create_element(type="photo", x=10, y=10, w=100, h=300, field_name="foto", side="front")
chk("Несколько элементов → первый на лицевой стороне", a2.photo_edit_target("foto")["aspect"] == 1.0 and a2.photo_edit_target("foto")["side"] == "front", a2.photo_edit_target("foto"))
d1.done(0); d2.done(0); a2.close()
dfree = pe.PhotoEditor(str(FACEP), api, None, field_name="foto2"); rf = dfree.frame.rect()
dfree.frame.resize_corner("br", QPointF(rf.right() - 60, rf.bottom() - 5), rf); rf2 = dfree.frame.rect()
chk("Без привязанного элемента: рамка свободная, статус сообщает", dfree.aspect is None and dfree.status.text() == "В шаблоне нет фото-элемента, пропорции свободные" and abs(rf2.width() / rf2.height() - rf.width() / rf.height()) > 0.05, (dfree.status.text(), rf.width() / rf.height(), rf2.width() / rf2.height()))
dfree.update_preview(); dfree.reset_frame(); app.processEvents()
chk("D46: после обновления превью/рамки статус свободной рамки сохраняется", dfree.status.text() == "В шаблоне нет фото-элемента, пропорции свободные", dfree.status.text())
dfree.done(0)

# ---- ползунки, превью ----
d = pe.PhotoEditor(str(FACEP), api, None, field_name="foto"); d.resize(760, 900); d.show(); app.processEvents(); QTest.qWait(50)
rng = {k: (d.sl[k].minimum(), d.sl[k].maximum(), d.sp[k].minimum(), d.sp[k].maximum()) for k in d.sl}
exp = {"brightness": (-50, 50), "contrast": (-50, 50), "scale": (10, 400), "rotate": (-180, 180)}
chk("Ползунки + поле: диапазоны", all(rng[k] == (*v, *v) for k, v in exp.items()), rng)
chk("Ползунки: начальные 0/0/100/0", [d.sp[k].value() for k in ("brightness", "contrast", "scale", "rotate")] == [0, 0, 100, 0])
if SHOTS: d.grab().save(str(QA / "stage14_raw.png"))
d.sl["brightness"].setValue(30); b0 = d.pix.pixmap().toImage(); QTest.qWait(150)
chk("Превью сразу (≤150 мс) = Backend apply_photo_edit", d.pix.pixmap().toImage() != b0 and d.img.tobytes() == bapi.apply_photo_edit(d.src, d.params(crop=False)).tobytes())
d.sp["brightness"].setValue(0); d.sp["rotate"].setValue(90); QTest.qWait(150)
chk("Вращать 90° (640×800 → 800×640)", d.img.size == (d.src.height, d.src.width), (d.src.size, d.img.size))
d.sp["rotate"].setValue(0); d.sp["scale"].setValue(50); QTest.qWait(150)
chk("Масштаб 50 %", abs(d.img.width - d.src.width / 2) <= 1, d.img.size); d.sp["scale"].setValue(100); QTest.qWait(150)

# ---- рамка ----
fr = d.frame; r = fr.rect()
chk("Рамка пунктирная, пропорции элемента", fr.pen().style() == Qt.PenStyle.DashLine and abs(r.width() / r.height() - ASPECT) < 0.01, (r.width(), r.height()))
fr.move_by(QPointF(-20, -15), r); r2 = fr.rect()
chk("Рамка перетаскивается", (r2.x(), r2.y()) != (r.x(), r.y()) and abs(r2.width() - r.width()) < 1e-6)
fr.resize_corner("br", QPointF(r2.right() - 60, r2.bottom() - 5), r2); r3 = fr.rect()
chk("Угол: размер с сохранением пропорций", abs(r3.width() - r2.width()) > 1 and abs(r3.width() / r3.height() - ASPECT) < 0.01, (r3.width(), r3.height()))
fr.resize_corner("tl", QPointF(-5000, -5000), r3); r4 = fr.rect()
chk("Рамка в границах изображения", fr.bounds.contains(r4) and abs(r4.width() / r4.height() - ASPECT) < 0.01)
d.reset_frame(); app.processEvents()
def dashed_sides(dlg):
    img = dlg.view.viewport().grab().toImage(); dr = dlg.frame.visible_device_rect().toRect()
    def hits(pts): return sum(1 for x, y in pts if 0 <= x < img.width() and 0 <= y < img.height() and (lambda c: c.blue() > 180 and c.red() < 120)(QColor(img.pixel(x, y))))
    side = {"top": [(x, y) for x in range(dr.left() + 3, dr.right() - 3) for y in range(dr.top(), dr.top() + 3)],
            "left": [(x, y) for y in range(dr.top() + 3, dr.bottom() - 3) for x in range(dr.left(), dr.left() + 3)],
            "bottom": [(x, y) for x in range(dr.left() + 3, dr.right() - 3) for y in range(dr.bottom() - 2, dr.bottom() + 1)],
            "right": [(x, y) for y in range(dr.top() + 3, dr.bottom() - 3) for x in range(dr.right() - 2, dr.right() + 1)]}
    return {k: hits(v) for k, v in side.items()}

# ---- Портрет ----
g = np.asarray(d.img.convert("L")); faces = cv2.CascadeClassifier(bpe.cascade_path()).detectMultiScale(g, 1.1, 5, minSize=(max(20, min(g.shape) // 12),) * 2)
fx, fy, fw, fh = (float(v) for v in max(faces, key=lambda t: t[2] * t[3]))
crown, chin = fy - 0.25 * fh, fy + fh
d.portrait.setChecked(True); app.processEvents(); QTest.qWait(50); x, y, w, h = d.crop()
chk("Портрет: лицо найдено, рамка поставлена", "не найдено" not in d.status.text() and d.portrait.isChecked(), (x, y, w, h))
head = (chin - crown) / h; room = (crown - y) / h
chk("Портрет: голова (макушка=Haar−0.25·fh … подбородок) 45–55 % высоты", 0.45 <= head <= 0.55, round(head, 3))
chk("Портрет: запас над макушкой 5–15 %", 0.05 <= room <= 0.15, round(room, 3))
chk("Портрет: макушка не срезана (верх рамки выше макушки)", y < crown, (y, round(crown, 1)))
chk("Портрет: лицо по центру (±5 % ширины)", abs((x + w / 2) - (fx + fw / 2)) <= 0.05 * w, (x + w / 2, fx + fw / 2))
chk("Портрет: ниже подбородка ≥30 % рамки (шея/плечи)", (y + h - chin) / h >= 0.30, round((y + h - chin) / h, 3))
chk("Портрет: пропорции рамки сохранены", abs(w / h - ASPECT) < 0.01, round(w / h, 4))
sides = dashed_sides(d)
chk("D42: видны все 4 стороны пунктира (пиксели)", all(v >= 5 for v in sides.values()), sides)
if SHOTS: d.grab().save(str(QA / "stage14_portrait.png"))
big = Image.open(FACEP).crop((120, 40, 520, 420)); big.save(SRC / "tight.jpg")   # лицо крупно, рамка не помещается
dt = pe.PhotoEditor(str(SRC / "tight.jpg"), api, None, field_name="foto"); dt.portrait.setChecked(True); tx, ty, tw, th = dt.crop()
chk("Портрет: рамка больше фото → сдвиг/уменьшение, в границах, пропорции", tx >= 0 and ty >= 0 and tx + tw <= dt.img.width and ty + th <= dt.img.height and abs(tw / th - ASPECT) < 0.01, ((tx, ty, tw, th), dt.img.size)); dt.done(0)
dn = pe.PhotoEditor(str(SRC / "noface.png"), api, None, field_name="foto"); c0 = dn.crop(); dn.portrait.setChecked(True)
chk("Портрет без лица: рамка не меняется, «Лицо не найдено»", dn.crop() == c0 and dn.status.text().startswith("Лицо не найдено"), dn.status.text()); dn.done(0)

# ---- Автоэффект ----
low = Image.fromarray((np.asarray(Image.open(FACEP).convert("RGB")) * 0.3 + 20).astype("uint8")); low.save(SRC / "low.png")
da = pe.PhotoEditor(str(SRC / "low.png"), api, None, field_name="foto"); m0 = ImageStat.Stat(da.img.convert("L")).mean[0]
da.autoeffect.setChecked(True); QTest.qWait(150); m1 = ImageStat.Stat(da.img.convert("L")).mean[0]; ex = da.img.convert("L").getextrema()
chk("Автоэффект: средняя → ~128, контраст растянут", abs(m1 - 128) < 30 and abs(m1 - 128) < abs(m0 - 128) and ex[1] - ex[0] > 200, (round(m0), round(m1), ex))
ae = da.img.tobytes(); da.sp["brightness"].setValue(20); QTest.qWait(150)
chk("Автоэффект: ручные ползунки поверх", da.img.tobytes() != ae and ImageStat.Stat(da.img.convert("L")).mean[0] > m1); da.done(0)
d.portrait.setChecked(False); d.autoeffect.setChecked(True); QTest.qWait(150); d.portrait.setChecked(True); app.processEvents()
if SHOTS: d.grab().save(str(QA / "stage14_autoeffect.png"))
btn = [b.text() for b in d.findChildren(QPushButton)]
chk("Внизу только «Применить» и «Отмена», нет «УгЧ»", "Применить" in btn and "Отмена" in btn and not any("УгЧ" in t for t in btn), btn); d.done(0)

# ---- умолчания, D41 ----
fresh = project("fresh", 330, 413); df = pe.PhotoEditor(str(FACEP), fresh, None, field_name="foto")
chk("«По умолчанию» без сохранённых → 0/0/100/0, без галочек", [df.sp[k].value() for k in ("brightness", "contrast", "scale", "rotate")] == [0, 0, 100, 0] and not df.autoeffect.isChecked() and not df.portrait.isChecked())
for k, v in (("brightness", 12), ("contrast", -7), ("scale", 150), ("rotate", 5)): df.sp[k].setValue(v)
df.autoeffect.setChecked(True); df.portrait.setChecked(True); df.save_defaults()
row = json.loads(sqlite3.connect(TMP / "fresh.db").execute("SELECT value FROM project_settings WHERE key='photo_edit_defaults'").fetchone()[0])
chk("«Установить по умолчанию» → project_settings (с portrait)", row.get("brightness") == 12 and row.get("portrait") is True and row.get("autoeffect") is True, row)
df.sp["brightness"].setValue(0); df.autoeffect.setChecked(False); df.portrait.setChecked(False); df.load_defaults()
chk("D41: «По умолчанию» восстанавливает параметры и «Портрет»", [df.sp[k].value() for k in ("brightness", "contrast", "scale", "rotate")] == [12, -7, 150, 5] and df.autoeffect.isChecked() and df.portrait.isChecked())
df.done(0); df2 = pe.PhotoEditor(str(FACEP), fresh, None, field_name="foto")
chk("D41: новый редактор открывается с «Портрет» из умолчаний", df2.portrait.isChecked() and df2.sp["scale"].value() == 150); df2.done(0); fresh.close()

# ---- Применить/Сохранить/Отмена, D43, 300 DPI ----
PH = TMP / "p/photos"; ls = lambda: set(os.listdir(PH))
pe.editor_hook = lambda dlg: (dlg.portrait.setChecked(True), dlg.apply())[1]
h0, hs = md5(PH / "orig.jpg"), md5(FACEP); f0 = ls()
f = RecordForm(api, pid); f.show(); blk = f.image_edits["foto"]; blk.edit_photo(); app.processEvents()
chk("Применить: БД не меняется до «Сохранить»", api.get_person(pid)["fields"]["foto"] == "photos/orig.jpg")
newp = blk.path; f.save(); app.processEvents(); saved = api.get_person(pid)["fields"]["foto"]
chk("Применить+Сохранить: путь в поле image, файл есть", saved == newp and saved != "photos/orig.jpg" and (TMP / "p" / saved).is_file(), saved)
chk("Исходники не изменены (md5)", md5(PH / "orig.jpg") == h0 and md5(FACEP) == hs)
outsz = Image.open(TMP / "p" / saved).size
chk("Выходной размер = элемент при 300 DPI (photo_edit_target.size)", outsz == tuple(TG["size"]), (outsz, TG["size"]))
if SHOTS:
    fc = RecordForm(api, pid); fc.show(); fc.update_preview(); app.processEvents(); fc.preview.grab().save(str(QA / "stage14_card.png")); fc.reject()
f1 = ls(); f = RecordForm(api, pid); f.show(); f.image_edits["foto"].edit_photo(); created = ls() - f1; f.reject(); app.processEvents()
chk("D43: «Отмена» формы — созданный в сессии файл удалён, запись не изменилась", created and not (created & ls()) and api.get_person(pid)["fields"]["foto"] == saved, (created, getattr(f, "discarded", None)))
chk("D43: файл записи и исходники не удалены при «Отмена»", (PH / pathlib.Path(saved).name).is_file() and (PH / "orig.jpg").is_file() and FACEP.is_file())
shutil.copy(FACE, PH / "loose.jpg"); hl = md5(PH / "loose.jpg")
for lbl, srcf in (("вне проекта", FACEP), ("уже в photos/", PH / "loose.jpg")):
    before = ls(); f = RecordForm(api); f.show(); eb = f.image_edits["foto"]; eb.from_file(str(srcf)); cp = eb.path; made = ls() - before
    chk(f"D43 «Из файла…» ({lbl}): создана копия в photos/", cp and cp.startswith("photos/") and pathlib.Path(cp).name != srcf.name and made == {pathlib.Path(cp).name}, (cp, made))
    f.reject(); app.processEvents()
    chk(f"D43 «Из файла…» ({lbl}) + «Отмена»: удалена только копия, источник цел", not (made & ls()) and srcf.is_file() and md5(srcf) == (hs if srcf == FACEP else hl), getattr(f, "discarded", None))
f = RecordForm(api); f.show(); f.edits["last_name"].setText("Новый"); f.image_edits["foto"].from_file(str(FACEP)); f.image_edits["foto"].edit_photo(); np_ = f.image_edits["foto"].path; f.save()
chk("D43: «Сохранить» — файл сессии остаётся", np_ and (TMP / "p" / np_).is_file(), np_)
pe.editor_hook = lambda dlg: (dlg.reject(), 0)[1]; f2 = ls()
f = RecordForm(api, pid); f.show(); f.image_edits["foto"].edit_photo(); f.save()
chk("«Отмена» редактора: без изменений и файлов", api.get_person(pid)["fields"]["foto"] == saved and ls() == f2)

# ---- EXIF ----
im = Image.open(FACEP).convert("RGB").transpose(Image.Transpose.ROTATE_90); e6 = Image.Exif(); e6[0x0112] = 6; im.save(SRC / "exif.jpg", exif=e6, quality=95)
de = pe.PhotoEditor(str(SRC / "exif.jpg"), api, None, field_name="foto"); tr = bapi.load_photo_for_edit(str(SRC / "exif.jpg"))
chk("EXIF: превью с учётом ориентации (640×800)", de.src.size == tr.size == Image.open(FACEP).size, (im.size, de.src.size))
de.portrait.setChecked(True); crop = de.crop(); prm = de.params(); rel = api.apply_and_save_photo(str(SRC / "exif.jpg"), prm)
out = Image.open(TMP / "p" / rel).convert("RGB"); exp_ = bapi.apply_photo_edit(tr, prm).convert("RGB").resize(out.size)
diff = float(np.abs(np.asarray(out, int) - np.asarray(exp_, int)).mean())
chk("EXIF: сохранённый кадр = рамка превью (содержимое, разница <6/255)", diff < 6, (out.size, crop, round(diff, 2))); de.done(0)

# ---- дубли / ui без обработки ----
uis = {p.name: p.read_text(encoding="utf-8").splitlines() for p in (ROOT / "ui").glob("*.py") if p.name not in ("smoke_test.py", "qa_click_all.py", "self_test.py")}
grep = lambda rx: [f"{n}:{i}" for n, ls_ in uis.items() for i, l in enumerate(ls_, 1) if re.search(rx, l) and not l.lstrip().startswith("#")]
chk("Дубли: нет обработки изображений в ui/", not grep(r"ImageEnhance|ImageOps|ImageFilter|\bcv2\b|import numpy|Image\.open|autocontrast|exif_transpose|\bimg\.(rotate|resize|crop|transpose)\("), grep(r"ImageEnhance|ImageOps|ImageFilter|\bcv2\b|import numpy|Image\.open|autocontrast|exif_transpose|\bimg\.(rotate|resize|crop|transpose)\("))
ratio = grep(r"""\[["']w["']\]\s*/\s*\w*\[?["']?h|\.w\s*/\s*\w+\.h|width_mm\s*/|25\.4""")
chk("Дубли: пропорции не вычисляются в ui/ (только photo_edit_target)", not ratio, ratio)
dele = [f"{n}:{i}" for n, ls_ in uis.items() for i, l in enumerate(ls_, 1) if re.search(r"os\.remove|(?<!self)\.unlink\(|shutil\.rmtree|os\.unlink", l) and "captured" not in l]
chk("Дубли: в ui/ нет удаления файлов фото (кроме временного снимка) — только Backend discard_photo", not dele, dele)
cnt = sum(len(re.findall(r"(?<!class )PhotoEditor\(", "\n".join(v))) for v in uis.values())
chk("Дубли: PhotoEditor создаётся в одном месте, QAction одной фабрикой", cnt == 1 and len(grep(r"make_edit_action\(")) == 2, (cnt, grep(r"make_edit_action\(")))

# ---- зависимости, spec, CI, миграция, тесты ----
req = (ROOT / "requirements.txt").read_text(); spec = (ROOT / "packaging/badge_generator.spec").read_text(); ci = (ROOT / ".github/workflows/build-windows.yml").read_text()
chk("requirements opencv-python-headless>=4.8,<5; spec каскад+манифест; CI MISSING", re.search(r"^opencv-python-headless>=4\.8,<5", req, re.M) and "haarcascade_frontalface_default.xml" in spec and 'like "MISSING*"' in ci)
old = TMP / "old.db"; c = bapi.connect(str(old)); bapi.upsert_field(c, "last_name", "Фамилия", 0); bapi.create_person(c, {"last_name": "Old"})
c.execute("DROP TABLE project_settings"); c.execute("PRAGMA user_version=5"); c.commit(); c.close()
c = bapi.connect(str(old)); v = c.execute("PRAGMA user_version").fetchone()[0]
chk("Миграция v5→v6: project_settings, данные целы", v == bdb.LATEST and c.execute("SELECT 1 FROM sqlite_master WHERE name='project_settings'").fetchone() and c.execute("SELECT COUNT(*) FROM persons").fetchone()[0] == 1, v); c.close()
tt = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "tests").glob("test_*photo*.py")) + "".join(p.read_text(encoding="utf-8") for p in (ROOT / "tests").glob("test_d4[0-3]*.py"))
chk("Тесты Backend: параметры, портрет с лицом/без, автоэффект, D41–D43", all(re.search(k, tt, re.I) for k in ("brightness", "face", "noface|no_face|без лиц", "autoeffect", "portrait", "discard")))

api.close(); n_ok = sum(r[1] for r in RES)
(TMP / "e2e_stage14_results.json").write_text(json.dumps(RES, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"ИТОГО: {n_ok}/{len(RES)} PASS; tmp={TMP}"); sys.exit(0 if n_ok == len(RES) else 1)
