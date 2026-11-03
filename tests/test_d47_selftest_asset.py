"""D47: встроенное фото для --self-test (Frontend) — badge_backend/assets/selftest_face.jpg."""
from pathlib import Path
import badge_backend
from badge_backend.services.photo_edit import detect_face_crop, load_photo_for_edit

def test_embedded_selftest_photo_detects_face():
    p = Path(badge_backend.__file__).resolve().parent / "assets" / "selftest_face.jpg"
    crop = detect_face_crop(load_photo_for_edit(p), 0.778)
    assert crop is not None and crop[2] > 0 and crop[3] > 0

def test_spec_and_ci_require_cascade():
    root = Path(__file__).resolve().parents[1]
    spec = (root / "packaging/badge_generator.spec").read_text(encoding="utf-8")
    ci = (root / ".github/workflows/build-windows.yml").read_text(encoding="utf-8")
    assert "raise SystemExit" in spec and "WARNING: haarcascade" not in spec and "selftest_face.jpg" in spec
    assert "required in bundle" in ci and "haarcascade_frontalface_default.xml" in ci
