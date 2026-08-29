"""ensure_thumbnails: real Pillow images against an in-memory storage fake."""
import io
import logging

from PIL import Image, ImageOps

from app.services.thumbnails import ensure_thumbnails


class FakeStorage:
    """Mimics AudioStorageService's method names over a dict."""

    def __init__(self, objects: dict[str, bytes] | None = None):
        self.objects = dict(objects or {})
        self.writes: list[str] = []

    def get_object_bytes(self, key: str) -> bytes:
        return self.objects[key]

    def write_object(self, key: str, data: bytes, content_type: str | None = None) -> None:
        self.objects[key] = data
        self.writes.append(key)

    def list_keys_with_prefix(self, prefix: str) -> list[str]:
        return sorted(k for k in self.objects if k.startswith(prefix))


def jpeg(width: int, height: int, *, orientation: int | None = None) -> bytes:
    img = Image.new("RGB", (width, height), "red")
    buf = io.BytesIO()
    kwargs = {}
    if orientation is not None:
        exif = Image.Exif()
        exif[0x0112] = orientation
        kwargs["exif"] = exif.tobytes()
    img.save(buf, "JPEG", **kwargs)
    return buf.getvalue()


def png(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (width, height), (0, 255, 0, 128)).save(buf, "PNG")
    return buf.getvalue()


def test_writes_a_jpeg_thumb_per_key_bounded_by_max_side():
    s = FakeStorage({"in/0001.jpg": jpeg(1600, 1200), "in/0002.png": png(300, 900)})
    out = ensure_thumbnails(s, ["in/0001.jpg", "in/0002.png"], "th/", max_side=256)
    assert out == {"in/0001.jpg": "th/0001.jpg", "in/0002.png": "th/0002.jpg"}
    t1 = Image.open(io.BytesIO(s.objects["th/0001.jpg"]))
    assert t1.format == "JPEG" and t1.size == (256, 192)
    t2 = Image.open(io.BytesIO(s.objects["th/0002.jpg"]))
    assert t2.format == "JPEG" and t2.mode == "RGB" and t2.size == (85, 256)


def test_exif_orientation_6_comes_out_upright():
    s = FakeStorage({"in/0001.jpg": jpeg(800, 400, orientation=6)})
    ensure_thumbnails(s, ["in/0001.jpg"], "th/", max_side=200)
    t = Image.open(io.BytesIO(s.objects["th/0001.jpg"]))
    assert t.size == (100, 200)  # rotated 90°: portrait
    assert ImageOps.exif_transpose(t).size == t.size  # no orientation tag left behind


def test_existing_thumbs_are_not_regenerated():
    s = FakeStorage({"in/0001.jpg": jpeg(100, 100), "th/0001.jpg": b"keep"})
    out = ensure_thumbnails(s, ["in/0001.jpg"], "th/")
    assert out == {"in/0001.jpg": "th/0001.jpg"}
    assert s.writes == []
    assert s.objects["th/0001.jpg"] == b"keep"


def test_corrupt_source_is_skipped_not_raised(caplog):
    s = FakeStorage({"in/0001.jpg": jpeg(100, 100), "in/0002.jpg": b"not an image"})
    with caplog.at_level(logging.WARNING):
        out = ensure_thumbnails(s, ["in/0001.jpg", "in/0002.jpg"], "th/")
    assert out == {"in/0001.jpg": "th/0001.jpg"}
    assert "in/0002.jpg" in caplog.text


def test_empty_keys_returns_empty_and_writes_nothing():
    s = FakeStorage()
    assert ensure_thumbnails(s, [], "th/") == {}
    assert s.writes == []
