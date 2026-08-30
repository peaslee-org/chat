"""Final outputs: GLB from the textured OBJ (trimesh, no GPU/EGL) and a PNG preview from a photo."""
import math
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageOps

DEFAULT_MAX_TEXTURE_SIZE = 4096
JPEG_QUALITY = 85

# COLMAP (and so OpenMVS) reconstruct in the computer-vision camera frame: x right, y DOWN,
# z forward, with the world anchored to the first registered image. glTF viewers put +y UP.
# A 180° rotation about x maps one to the other; being a proper rotation (det +1) it keeps
# winding, normals and texture coordinates valid. Orientation still follows how level the
# photos were held — see docs/TODO.md for gravity alignment.
CV_TO_GLTF = np.diag([1.0, -1.0, -1.0, 1.0])


def obj_to_glb(obj: Path, out: Path, max_texture_size: int = DEFAULT_MAX_TEXTURE_SIZE) -> Path:
    # One geometry per OBJ material, exported as separate glTF primitives. `force="mesh"` would
    # concatenate them and re-pack every atlas into one image — unbounded memory on large scans.
    scene = trimesh.load(obj, force="scene", process=False)
    for geometry in scene.geometry.values():
        geometry.apply_transform(CV_TO_GLTF)
        shrink_atlas(geometry, max_texture_size)
    out.parent.mkdir(parents=True, exist_ok=True)
    scene.export(out, file_type="glb")
    return out


def shrink_atlas(geometry: trimesh.Trimesh, max_texture_size: int) -> None:
    """Crop the geometry's texture to the box its UVs actually use, cap its long edge, and mark it
    for JPEG embedding. OpenMVS writes square power-of-two atlases and packs only part of the last
    one, so a big scan embedded two mostly-empty 8192² PNGs (45 MB). In place; UVs are remapped."""
    visual = geometry.visual
    material = getattr(visual, "material", None)
    image = getattr(material, "image", None)
    uv = getattr(visual, "uv", None)
    if image is None or uv is None or len(uv) == 0 or getattr(image, "encoderinfo", None):
        return      # nothing to shrink, or this material was already shrunk (shared between geometries)
    w, h = image.size
    u0, v0 = np.clip(uv.min(axis=0), 0.0, 1.0)
    u1, v1 = np.clip(uv.max(axis=0), 0.0, 1.0)
    # UV origin is bottom-left; image rows count from the top. Snap outwards to whole texels; a box
    # pinned to the far edge (all u == 1) still gets one texel rather than an empty crop.
    x0, top = min(math.floor(u0 * w), w - 1), min(math.floor((1 - v1) * h), h - 1)
    x1, bottom = min(w, max(math.ceil(u1 * w), x0 + 1)), min(h, max(math.ceil((1 - v0) * h), top + 1))
    cropped = image.convert("RGB").crop((x0, top, x1, bottom))
    cw, ch = cropped.size
    visual.uv = np.column_stack([(uv[:, 0] * w - x0) / cw, (uv[:, 1] * h - (h - bottom)) / ch])
    if max(cw, ch) > max_texture_size:
        scale = max_texture_size / max(cw, ch)
        cropped = cropped.resize((max(1, round(cw * scale)), max(1, round(ch * scale))), Image.LANCZOS)
    # trimesh keeps a PIL image whose .format is JPEG as JPEG — but re-encodes it with Pillow's
    # defaults, so hand it the raw pixels (never JPEG-encoded) and the quality via encoderinfo.
    cropped.format = "JPEG"
    cropped.encoderinfo = {"quality": JPEG_QUALITY}
    material.image = cropped


def make_preview(image: Path, out: Path, max_edge: int = 640) -> Path:
    with Image.open(image) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((max_edge, max_edge))   # never upscales, keeps aspect
        out.parent.mkdir(parents=True, exist_ok=True)
        im.save(out, format="PNG")
    return out
