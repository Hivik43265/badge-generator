"""Поиск TTF с кириллицей (DejaVu → Liberation → Noto → любой TTF → встроенный Pillow)."""
import functools, glob, os
from PIL import ImageFont
_DIRS = ["/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts"),
         "C:/Windows/Fonts", "/Library/Fonts", "/System/Library/Fonts"]
_FAMILIES = {
    "dejavu sans": ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
    "dejavu serif": ("DejaVuSerif.ttf", "DejaVuSerif-Bold.ttf"),
    "dejavu sans mono": ("DejaVuSansMono.ttf", "DejaVuSansMono-Bold.ttf"),
    "arial": ("arial.ttf", "arialbd.ttf"),
    "liberation sans": ("LiberationSans-Regular.ttf", "LiberationSans-Bold.ttf"),
}
DEFAULT_FAMILY = "dejavu sans"

@functools.lru_cache(None)
def _find(fname):
    for d in _DIRS:
        hits = glob.glob(os.path.join(d, "**", fname), recursive=True)
        if hits: return hits[0]
    return None

@functools.lru_cache(None)
def find_font_path(family=None, bold=False):
    """Путь к TTF для семейства или None (будет встроенный шрифт Pillow)."""
    for fam in (family, DEFAULT_FAMILY, "liberation sans", "arial"):
        if fam and fam.lower() in _FAMILIES:
            p = _find(_FAMILIES[fam.lower()][1 if bold else 0])
            if p: return p
    for pat in ("Noto*Sans*Regular.ttf", "*.ttf"):
        p = _find(pat)
        if p: return p
    return None

@functools.lru_cache(512)
def get_font(size_px, family=None, bold=False, font_path=None):
    size_px = max(1, int(size_px))
    for p in (font_path, find_font_path(family, bold)):
        if p and os.path.exists(p):
            try: return ImageFont.truetype(p, size_px)
            except OSError: pass
    try: return ImageFont.load_default(size_px)
    except TypeError: return ImageFont.load_default()
