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


def write_two_material_quads(d: Path) -> Path:
    Image.new("RGB", (2, 2), (255, 0, 0)).save(d / "a.png")
    Image.new("RGB", (4, 4), (0, 0, 255)).save(d / "b.png")
    (d / "two.mtl").write_text("newmtl ma\nmap_Kd a.png\nnewmtl mb\nmap_Kd b.png\n")
    (d / "two.obj").write_text(
        "mtllib two.mtl\n"
        "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\n"
        "v 2 0 0\nv 3 0 0\nv 3 1 0\nv 2 1 0\n"
        "vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\n"
        "usemtl ma\nf 1/1 2/2 3/3\nf 1/1 3/3 4/4\n"
        "usemtl mb\nf 5/1 6/2 7/3\nf 5/1 7/3 8/4\n"
    )
    return d / "two.obj"


def test_multi_material_obj_exports_one_primitive_per_material_without_repacking(tmp_path):
    """OpenMVS writes one material per atlas (two 8192² atlases on a big scan). Forcing a single
    mesh made trimesh concatenate the geometries and re-pack both textures into one image —
    the step that ran out of memory on 2026-08-28. Keep them as separate primitives."""
    obj = write_two_material_quads(tmp_path)
    scene = trimesh.load(obj_to_glb(obj, tmp_path / "mesh.glb"), force="scene")
    geoms = list(scene.geometry.values())
    assert len(geoms) == 2
    sizes = sorted(g.visual.material.baseColorTexture.size for g in geoms)
    assert sizes == [(2, 2), (4, 4)]                     # textures untouched, not merged
    assert all(np.isclose(g.vertices[:, 1].min(), -1.0) for g in geoms)  # rotation on every geom
    assert all(g.visual.uv.shape == (len(g.vertices), 2) for g in geoms)  # UVs survive per-geom


# ── atlas shrinking ──────────────────────────────────────────────────────────
# OpenMVS writes square power-of-two atlases (8192² on a big scan) and only packs the top-left
# part of the last one; embedding them uncropped, as PNG, made the 51-photo GLB 45 MB.

def write_quad_using_part_of_atlas(d: Path) -> Path:
    """8×8 atlas: green where the quad's UVs point (u 0.25–0.5, v 0.5–1 → columns 2–3, rows 0–3
    from the top), red everywhere else."""
    im = Image.new("RGB", (8, 8), (255, 0, 0))
    for x in range(2, 4):
        for y in range(0, 4):
            im.putpixel((x, y), (0, 255, 0))
    im.save(d / "tex.png")
    (d / "part.mtl").write_text("newmtl m\nmap_Kd tex.png\n")
    (d / "part.obj").write_text(
        "mtllib part.mtl\n"
        "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\n"
        "vt 0.25 0.5\nvt 0.5 0.5\nvt 0.5 1\nvt 0.25 1\n"
        "usemtl m\nf 1/1 2/2 3/3\nf 1/1 3/3 4/4\n"
    )
    return d / "part.obj"


def glb_images(glb: Path) -> list[tuple[str, bytes]]:
    """(mimeType, bytes) for every image embedded in a GLB, straight from the container."""
    import json, struct
    data = glb.read_bytes()
    json_len = struct.unpack_from("<I", data, 12)[0]
    header = json.loads(data[20:20 + json_len])
    bin_start = 20 + json_len + 8
    out = []
    for img in header["images"]:
        view = header["bufferViews"][img["bufferView"]]
        off = bin_start + view.get("byteOffset", 0)
        out.append((img["mimeType"], data[off:off + view["byteLength"]]))
    return out


def test_atlas_is_cropped_to_the_used_uv_box_and_uvs_remapped(tmp_path):
    obj = write_quad_using_part_of_atlas(tmp_path)
    mesh = trimesh.load(obj_to_glb(obj, tmp_path / "mesh.glb"), force="mesh")
    tex = mesh.visual.material.baseColorTexture
    assert tex.size == (2, 4)
    px = np.asarray(tex.convert("RGB"))
    assert (px[..., 1] > 200).all() and (px[..., 0] < 60).all()     # only the green part
    assert np.allclose(mesh.visual.uv.min(axis=0), [0.0, 0.0])
    assert np.allclose(mesh.visual.uv.max(axis=0), [1.0, 1.0])


def test_atlas_is_downscaled_to_max_texture_size(tmp_path):
    Image.new("RGB", (16, 16), (255, 0, 0)).save(tmp_path / "tex.png")
    (tmp_path / "quad.mtl").write_text("newmtl m\nmap_Kd tex.png\n")
    (tmp_path / "quad.obj").write_text(
        "mtllib quad.mtl\nv 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\n"
        "vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\nusemtl m\nf 1/1 2/2 3/3\nf 1/1 3/3 4/4\n")
    mesh = trimesh.load(obj_to_glb(tmp_path / "quad.obj", tmp_path / "mesh.glb", max_texture_size=8), force="mesh")
    assert mesh.visual.material.baseColorTexture.size == (8, 8)


def test_atlas_is_embedded_as_jpeg_encoded_once_at_quality_85(tmp_path):
    """Photo textures compress far better as JPEG than PNG. trimesh re-saves any PIL image whose
    .format is JPEG with Pillow's defaults, so the pixels must reach it un-encoded, carrying the
    quality we want — the bytes in the GLB then match a single q85 encode of the cropped atlas."""
    import io
    obj = write_quad_using_part_of_atlas(tmp_path)
    images = glb_images(obj_to_glb(obj, tmp_path / "mesh.glb"))
    assert [mime for mime, _ in images] == ["image/jpeg"]
    with Image.open(tmp_path / "tex.png") as im:
        expected = io.BytesIO()
        im.crop((2, 0, 4, 4)).save(expected, format="JPEG", quality=85)
    assert images[0][1].rstrip(b"\x00") == expected.getvalue()     # GLB pads views to 4 bytes


def test_uvs_pinned_to_the_far_corner_still_export_a_one_texel_atlas(tmp_path):
    """All UVs at (1, 0) put the used box on the atlas's right/bottom edge; the crop must not
    collapse to zero width (which made trimesh fail the whole job at publish)."""
    Image.new("RGB", (4, 4), (255, 0, 0)).save(tmp_path / "tex.png")
    (tmp_path / "c.mtl").write_text("newmtl m\nmap_Kd tex.png\n")
    (tmp_path / "c.obj").write_text(
        "mtllib c.mtl\nv 0 0 0\nv 1 0 0\nv 1 1 0\nvt 1 0\nusemtl m\nf 1/1 2/1 3/1\n")
    mesh = trimesh.load(obj_to_glb(tmp_path / "c.obj", tmp_path / "mesh.glb"), force="mesh")
    assert mesh.visual.material.baseColorTexture.size == (1, 1)


# ── vertex welding ───────────────────────────────────────────────────────────
# OpenMVS's OBJ indexes positions and UVs separately; loaded with process=False every face corner
# becomes its own vertex (3 per face — 86 k vertices for the 29 k-face sample, 2 MB of a 2.2 MB
# GLB; ~36 MB at 500 k faces). Weld corners that share position *and* UV; seams stay split.

def write_quad_with_per_corner_uvs(d: Path) -> Path:
    """OpenMVS layout: one `vt` line per face corner, so corners that share a position and the
    same UV *values* still have distinct vt indices — trimesh's index-pair dedup can't weld them."""
    Image.new("RGB", (2, 2), (255, 0, 0)).save(d / "tex.png")
    (d / "pc.mtl").write_text("newmtl m\nmap_Kd tex.png\n")
    (d / "pc.obj").write_text(
        "mtllib pc.mtl\n"
        "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\n"
        "vt 0 0\nvt 1 0\nvt 1 1\n"              # corners of face 1
        "vt 0 0\nvt 1 1\nvt 0 1\n"              # corners of face 2 (vt 4 == vt 1, vt 5 == vt 3)
        "usemtl m\nf 1/1 2/2 3/3\nf 1/4 3/5 4/6\n"
    )
    return d / "pc.obj"


def test_corners_sharing_position_and_uv_values_are_welded(tmp_path):
    obj = write_quad_with_per_corner_uvs(tmp_path)
    mesh = trimesh.load(obj_to_glb(obj, tmp_path / "mesh.glb"), force="mesh", process=False)
    assert len(mesh.faces) == 2
    assert len(mesh.vertices) == 4               # not 6
    assert mesh.visual.uv.shape == (4, 2)
    # UVs stayed with their positions through the weld: the fixture maps (x, y) → (u, v) and the
    # export flips y, so each vertex's uv is (x, -y).
    assert np.allclose(mesh.visual.uv, mesh.vertices[:, :2] * [1, -1])


def test_uv_seams_keep_their_own_vertices(tmp_path):
    """Two triangles share an edge in space but map it to different atlas patches — the shared
    positions must stay as separate vertices or one side's texture would be wrong."""
    Image.new("RGB", (4, 4), (255, 0, 0)).save(tmp_path / "tex.png")
    (tmp_path / "s.mtl").write_text("newmtl m\nmap_Kd tex.png\n")
    (tmp_path / "s.obj").write_text(
        "mtllib s.mtl\n"
        "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\n"
        "vt 0 0\nvt 0.5 0\nvt 0.5 0.5\n"          # patch A for the first triangle
        "vt 0.5 0.5\nvt 1 1\nvt 0.5 1\n"          # patch B for the second: v1 and v3 get new UVs
        "usemtl m\nf 1/1 2/2 3/3\nf 1/4 3/5 4/6\n"
    )
    mesh = trimesh.load(obj_to_glb(tmp_path / "s.obj", tmp_path / "mesh.glb"), force="mesh", process=False)
    assert len(mesh.faces) == 2
    assert len(mesh.vertices) == 6               # 4 positions, but v1/v3 differ in UV per side


def test_texture_cap_is_by_area_so_a_thin_strip_keeps_its_resolution(tmp_path):
    """OpenMVS packs a small scan into a strip along the top of a square atlas (8192×250 on the
    sample). Capping the long edge halved its texel density for no byte reason; the budget is
    max_texture_size² pixels, so the strip fits untouched while a full 16×16 still becomes 8×8."""
    Image.new("RGB", (32, 2), (255, 0, 0)).save(tmp_path / "tex.png")
    (tmp_path / "strip.mtl").write_text("newmtl m\nmap_Kd tex.png\n")
    (tmp_path / "strip.obj").write_text(
        "mtllib strip.mtl\nv 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\n"
        "vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\nusemtl m\nf 1/1 2/2 3/3\nf 1/1 3/3 4/4\n")
    mesh = trimesh.load(obj_to_glb(tmp_path / "strip.obj", tmp_path / "mesh.glb", max_texture_size=8), force="mesh")
    assert mesh.visual.material.baseColorTexture.size == (32, 2)     # 64 px ≤ 8² budget
