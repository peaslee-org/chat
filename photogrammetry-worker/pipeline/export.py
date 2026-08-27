"""Final outputs: GLB from the textured OBJ (trimesh, no GPU/EGL) and a PNG preview from a photo."""
from pathlib import Path

import trimesh
from PIL import Image, ImageOps


def obj_to_glb(obj: Path, out: Path) -> Path:
    mesh = trimesh.load(obj, force="mesh")
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
