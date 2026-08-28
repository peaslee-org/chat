"""GLB export from a textured OBJ; preview downscale keeps aspect."""
from pathlib import Path

import numpy as np
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
    mat = mesh.visual.material
    assert mat is not None
    # trimesh's GLB round-trip yields a PBRMaterial with the texture on baseColorTexture.
    assert mat.baseColorTexture.size == (2, 2)
    assert mesh.visual.uv.shape == (len(mesh.vertices), 2)


def test_obj_to_glb_rotates_colmap_frame_to_gltf_y_up(tmp_path):
    """COLMAP/OpenMVS coordinates are y-down, z-forward; glTF is y-up. Without the basis
    change the reconstruction renders upside down (observed on the sample scan 2026-08-28)."""
    obj = write_textured_quad(tmp_path)  # quad in the z=0 plane, vertices y ∈ [0, 1]
    mesh = trimesh.load(obj_to_glb(obj, tmp_path / "mesh.glb"), force="mesh")
    # y and z flip, x is untouched: (1, 1, 0) → (1, -1, 0)
    assert np.allclose(mesh.vertices.min(axis=0), [0, -1, 0])
    assert np.allclose(mesh.vertices.max(axis=0), [1, 0, 0])
    # a proper rotation, not a mirror: the face normal rotates with it (+z → -z) and winding holds
    assert np.allclose(mesh.face_normals[0], [0, 0, -1])
    assert mesh.visual.uv.shape == (len(mesh.vertices), 2)  # texture coordinates survive


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
