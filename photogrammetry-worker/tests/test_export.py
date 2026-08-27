"""GLB export from a textured OBJ; preview downscale keeps aspect."""
from pathlib import Path

import trimesh
from PIL import Image

from pipeline.export import make_preview, obj_to_glb


def write_textured_quad(d: Path) -> Path:
    Image.new("RGB", (2, 2), (255, 0, 0)).save(d / "tex.png")
    (d / "quad.mtl").write_text("newmtl m\nKd 1 1 1\nmap_Kd tex.png\n")
    (d / "quad.obj").write_text(
        "mtllib quad.mtl\n"
        "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\n"
        "vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\n"
        "usemtl m\nf 1/1 2/2 3/3\nf 1/1 3/3 4/4\n"
    )
    return d / "quad.obj"


def test_obj_to_glb_writes_binary_gltf_with_texture(tmp_path):
    obj = write_textured_quad(tmp_path)
    out = obj_to_glb(obj, tmp_path / "mesh.glb")
    data = out.read_bytes()
    assert data[:4] == b"glTF"
    mesh = trimesh.load(out, force="mesh")
    assert len(mesh.faces) == 2
    assert getattr(mesh.visual, "material", None) is not None


def test_make_preview_downscales_long_edge_and_keeps_aspect(tmp_path):
    Image.new("RGB", (1600, 1200), (0, 255, 0)).save(tmp_path / "in.jpg")
    out = make_preview(tmp_path / "in.jpg", tmp_path / "preview.png", max_edge=640)
    with Image.open(out) as im:
        assert im.size == (640, 480) and im.format == "PNG"


def test_make_preview_does_not_upscale(tmp_path):
    Image.new("RGB", (300, 200)).save(tmp_path / "in.png")
    out = make_preview(tmp_path / "in.png", tmp_path / "preview.png")
    with Image.open(out) as im:
        assert im.size == (300, 200)
