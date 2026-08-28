"""Make every photo the same pixel size before COLMAP.

COLMAP reads raw bitmaps (EXIF orientation ignored) and, with `--ImageReader.single_camera 1`,
silently drops any image whose size differs (`CAMERA_SINGLE_DIM_ERROR`). Phones auto-rotate: a
few landscape frames in a portrait set is the common case. Rotating those 90° keeps the same
camera (same focal, centred principal point) — structure-from-motion does not care about roll.
"""
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

_ORIENTATION = 0x0112


@dataclass(frozen=True)
class PhotoReport:
    usable: int
    rotated: list[str]
    skipped: list[str]
    unreadable: list[str] = field(default_factory=list)

    def warnings(self) -> list[str]:
        out = []
        if self.rotated:
            n = len(self.rotated)
            out.append(f"{n} photo{'s were' if n != 1 else ' was'} rotated to match the others (phone auto-rotate)")
        if self.skipped:
            n = len(self.skipped)
            names = ", ".join(self.skipped[:5]) + ("…" if n > 5 else "")
            out.append(f"{n} photo{'s have' if n != 1 else ' has'} a different resolution and "
                       f"{'were' if n != 1 else 'was'} skipped: {names}")
        if self.unreadable:
            n = len(self.unreadable)
            names = ", ".join(self.unreadable[:5]) + ("…" if n > 5 else "")
            out.append(f"{n} photo{'s' if n != 1 else ''} could not be read and "
                       f"{'were' if n != 1 else 'was'} skipped: {names}")
        return out


def _save(im: Image.Image, path: Path, exif) -> None:
    exif[_ORIENTATION] = 1
    kwargs = {"exif": exif.tobytes()}
    if path.suffix.lower() in (".jpg", ".jpeg"):
        kwargs["quality"] = 95
    im.save(path, **kwargs)


def normalise(images: Path, skipped_dir: Path) -> PhotoReport:
    files = sorted(p for p in images.iterdir() if p.is_file())
    sizes: dict[Path, tuple[int, int]] = {}
    unreadable: list[str] = []
    for p in files:
        try:
            with Image.open(p) as im:
                exif = im.getexif()
                if exif.get(_ORIENTATION, 1) != 1:
                    upright = ImageOps.exif_transpose(im)
                    _save(upright, p, exif)
                    sizes[p] = upright.size
                else:
                    sizes[p] = im.size
        except (UnidentifiedImageError, OSError):
            skipped_dir.mkdir(parents=True, exist_ok=True)
            p.rename(skipped_dir / p.name)
            unreadable.append(p.name)
    if not sizes:
        return PhotoReport(0, [], [], unreadable)
    majority = Counter(sizes.values()).most_common(1)[0][0]
    transposed = (majority[1], majority[0])
    rotated, skipped = [], []
    for p, size in sizes.items():
        if size == majority:
            continue
        if size == transposed:
            with Image.open(p) as im:
                exif = im.getexif()
                _save(im.transpose(Image.Transpose.ROTATE_90), p, exif)
            rotated.append(p.name)
        else:
            skipped_dir.mkdir(parents=True, exist_ok=True)
            p.rename(skipped_dir / p.name)
            skipped.append(p.name)
    return PhotoReport(usable=len(sizes) - len(skipped), rotated=rotated, skipped=skipped,
                        unreadable=unreadable)
