"""The committed sample assets are what the mock service serves — keep them small and clean."""
from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parents[2] / "app" / "assets" / "photogrammetry"


def test_images_exist_are_small_and_exif_free():
    images = sorted((ASSETS / "images").glob("*.jpg"))
    assert len(images) >= 5
    assert [p.name for p in images] == [f"{i:04d}.jpg" for i in range(1, len(images) + 1)]
    total = 0
    for p in images:
        with Image.open(p) as im:
            assert im.format == "JPEG"
            assert max(im.size) <= 640
            assert not im.getexif(), f"{p.name} still carries EXIF"
        total += p.stat().st_size
    assert total <= 2_500_000


def test_mesh_is_a_glb_and_preview_is_png():
    glb = (ASSETS / "mesh.glb").read_bytes()
    assert glb[:4] == b"glTF"
    assert len(glb) < 200_000
    with Image.open(ASSETS / "preview.png") as im:
        assert im.format == "PNG"
