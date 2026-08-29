"""Thumbnails for a scan's input photos, generated on demand and cached beside them in S3.

`ensure_thumbnails` is blocking (S3 round trips + Pillow); callers run it off the event loop.
"""
import io
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import PurePosixPath

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

THUMB_MAX_SIDE = 256
THUMB_QUALITY = 80


def thumb_key_for(key: str, thumb_prefix: str) -> str:
    return f"{thumb_prefix}{PurePosixPath(key).stem}.jpg"


def make_thumbnail(data: bytes, max_side: int = THUMB_MAX_SIDE) -> bytes:
    """Upright, RGB, at most `max_side` on the long edge, JPEG q80. Raises on undecodable input."""
    with Image.open(io.BytesIO(data)) as img:
        # JPEG: decode straight to a reduced size instead of the full raster (DCT scaling).
        img.draft("RGB", (max_side, max_side))
        img = ImageOps.exif_transpose(img) or img
        img.thumbnail((max_side, max_side))
        if img.mode != "RGB":
            img = img.convert("RGB")
        out = io.BytesIO()
        img.save(out, "JPEG", quality=THUMB_QUALITY, optimize=True)
        return out.getvalue()


def ensure_thumbnails(
    storage,
    keys: list[str],
    thumb_prefix: str,
    *,
    max_side: int = THUMB_MAX_SIDE,
    workers: int = 8,
) -> dict[str, str]:
    """Return {input key: thumbnail key}, generating any thumbnail that is not already stored.

    A source that can't be decoded is logged and left out of the map; it never fails the call.
    """
    if not keys:
        return {}
    existing = set(storage.list_keys_with_prefix(thumb_prefix))
    wanted = {key: thumb_key_for(key, thumb_prefix) for key in keys}
    missing = [key for key, tk in wanted.items() if tk not in existing]

    def build(key: str) -> bool:
        try:
            thumb = make_thumbnail(storage.get_object_bytes(key), max_side)
            storage.write_object(wanted[key], thumb, content_type="image/jpeg")
            return True
        except Exception:  # noqa: BLE001 — one bad photo must not hide the rest
            logger.warning("thumbnail failed for %s", key, exc_info=True)
            return False

    failed: set[str] = set()
    if missing:
        with ThreadPoolExecutor(max_workers=min(workers, len(missing))) as pool:
            for key, ok in zip(missing, pool.map(build, missing)):
                if not ok:
                    failed.add(key)
    return {key: tk for key, tk in wanted.items() if key not in failed}
