"""Загрузка фото для печати: кириллица в пути, относительное имя vs photos/, поле image, байты в поле."""
import io
from pathlib import Path
from PIL import Image
from badge_backend import api
from badge_backend.render import render_card_db
from badge_backend.services.photos import open_photo_file, resolve_photo_path

def _red(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 40), "red").save(path)
    return path

def _prj(tmp_path):
    con = api.connect(tmp_path / "project.db")
    api.upsert_field(con, "pic", "Фото", data_type="image")
    api.create_element(con, "photo", 0, 0, 100, 100, field_name="pic")
    return con

def _center(con, pid, base):
    return render_card_db(con, pid, "front", base).convert("RGB").getpixel((50, 50))

def test_render_image_field_relative_path(tmp_path):
    con = _prj(tmp_path)
    rel = api.save_photo(con, _red(tmp_path / "src.png").read_bytes(), ext="png", base_dir=tmp_path)
    pid = api.create_person(con, {"pic": rel})
    assert rel.startswith("photos/")
    assert _center(con, pid, tmp_path)[0] > 200

def test_resolve_filename_falls_back_to_photos_dir(tmp_path):
    _red(tmp_path / "photos" / "ivan.jpg")
    p = {"fields": {"pic": "ivan.jpg"}}
    assert resolve_photo_path(p, "pic", tmp_path) == (tmp_path / "photos" / "ivan.jpg").absolute()
    con = _prj(tmp_path)
    pid = api.create_person(con, {"pic": "ivan.jpg"})
    assert _center(con, pid, tmp_path)[0] > 200

def test_open_and_render_cyrillic_path(tmp_path):
    src = _red(tmp_path / "фото" / "Иван" / "снимок.jpg")
    im = open_photo_file(src)
    assert im.size == (40, 40)
    assert api.load_photo_for_edit(src).size == (40, 40)
    # относительный путь с кириллицей от base_dir
    rel = Path("фото") / "Иван" / "снимок.jpg"
    assert api.load_photo_for_edit(rel, tmp_path).size == (40, 40)
    con = _prj(tmp_path)
    pid = api.create_person(con, {"pic": str(rel).replace("\\", "/")})
    assert _center(con, pid, tmp_path)[0] > 200
    # абсолютный путь с кириллицей
    pid2 = api.create_person(con, {"pic": str(src)})
    assert _center(con, pid2, tmp_path)[0] > 200

def test_render_image_bytes_stored_as_latin1_text(tmp_path):
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "red").save(buf, "JPEG")
    raw = buf.getvalue().decode("latin-1")
    con = _prj(tmp_path)
    pid = api.create_person(con, {"pic": raw})
    # в JSON значение — не путь, а содержимое файла; render_card должен его прочитать
    assert _center(con, pid, tmp_path)[0] > 200
    assert api.load_photo_for_edit(raw).size == (40, 40)
