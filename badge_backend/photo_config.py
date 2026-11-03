"""photo_config = 'x;y;scale;crop_x;crop_y;angle' (ТЗ Архитектора, v2).

x, y         int, px холста: сдвиг фото внутри рамки (+x вправо, +y вниз) относительно центра рамки.
scale        float > 0: зум относительно cover-fit (1.0 = обрезанное фото ровно закрывает рамку).
crop_x/y     int, px исходника: левый верхний угол обрезки; используется область
             [crop_x..W, crop_y..H] исходного фото.
angle        float, градусы ПО ЧАСОВОЙ, поворот вокруг центра фото.
Default '0;0;1.0;0;0;0'. Невалидная строка -> default + warning (не исключение).
"""
import logging, warnings
from dataclasses import dataclass
log = logging.getLogger(__name__)
DEFAULT = "0;0;1.0;0;0;0"

@dataclass(frozen=True)
class PhotoConfig:
    x: int = 0; y: int = 0; scale: float = 1.0
    crop_x: int = 0; crop_y: int = 0; angle: float = 0.0

    @classmethod
    def parse(cls, s) -> "PhotoConfig":
        if s is None or not str(s).strip():
            return cls()
        try:
            p = [v.strip().replace(",", ".") for v in str(s).split(";")]
            if len(p) != 6: raise ValueError(f"нужно 6 значений, получено {len(p)}")
            def _int(v, name):
                f = float(v)
                if f != int(f): raise ValueError(f"{name} должен быть целым px")
                return int(f)
            x, y, cx, cy = (_int(p[i], n) for i, n in ((0, "x"), (1, "y"), (3, "crop_x"), (4, "crop_y")))
            sc, a = float(p[2]), float(p[5])
            if not sc > 0 or sc != sc or sc == float("inf"): raise ValueError("scale должен быть > 0")
            if cx < 0 or cy < 0: raise ValueError("crop_x/crop_y >= 0")
            if a != a or abs(a) == float("inf"): raise ValueError("angle некорректен")
            return cls(x, y, sc, cx, cy, a)
        except (ValueError, TypeError) as e:
            msg = f"photo_config {s!r} невалиден ({e}); используется {DEFAULT}"
            log.warning(msg); warnings.warn(msg, RuntimeWarning, stacklevel=2)
            return cls()

    def dump(self) -> str:
        # scale всегда с точкой ('1.0'); angle — '0' если целый, иначе '15.5'
        a = float(self.angle); a_s = str(int(a)) if a == int(a) else repr(a)
        return f"{self.x};{self.y};{float(self.scale)!r};{self.crop_x};{self.crop_y};{a_s}"

def normalize(s) -> str:
    return PhotoConfig.parse(s).dump()
