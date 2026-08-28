"""Final outputs: GLB from the textured OBJ (trimesh, no GPU/EGL) and a PNG preview from a photo."""
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageOps

# COLMAP (and so OpenMVS) reconstruct in the computer-vision camera frame: x right, y DOWN,
# z forward, with the world anchored to the first registered image. glTF viewers put +y UP.
# A 180° rotation about x maps one to the other; being a proper rotation (det +1) it keeps
# winding, normals and texture coordinates valid. Orientation still follows how level the
# photos were held — see docs/TODO.md for gravity alignment.
CV_TO_GLTF = np.diag([1.0, -1.0, -1.0, 1.0])


def obj_to_glb(obj: Path, out: Path) -> Path:
    mesh = trimesh.load(obj, force="mesh")
    mesh.apply_transform(CV_TO_GLTF)
    out.parent.mkdir(parents=True, exist_ok=True)
    mesh.export(out, file_type="glb")
    return out


def make_preview(image: Path, out: Path, max_edge: int = 640) -> Path:
    with Image.open(image) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((max_edge, max_edge))   # never upscales, keeps aspect
        out.parent.mkdir(parents=True, exist_ok=True)
        im.save(out, format="PNG")
    return out
