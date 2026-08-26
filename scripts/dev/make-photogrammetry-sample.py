#!/usr/bin/env python3
"""Build the committed photogrammetry sample assets for chat-api's mock mode.

Usage (from the repo root; none of these libraries are project dependencies):

  uv run --with pillow --with trimesh --with numpy python \
      scripts/dev/make-photogrammetry-sample.py --photos ~/Pictures/some-folder
      # real photos → downscaled, EXIF stripped
  uv run --with pillow --with trimesh --with numpy python \
      scripts/dev/make-photogrammetry-sample.py --synthetic
      # 12 drawn placeholder views instead

Always writes mesh.glb (a small procedural vertex-coloured object) and preview.png.
Prints the one-time `aws s3 sync` line for the shared prod sample set; it never touches AWS.
The repo is public: every image is re-encoded from pixels only, so no EXIF (GPS, device,
timestamps) survives.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw, ImageOps

DEFAULT_OUT = Path("chat-api/app/assets/photogrammetry")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic"}


def write_photo(src: Path, dest: Path, max_edge: int, quality: int) -> int:
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)          # bake orientation, then drop the tag
        im = im.convert("RGB")
        im.thumbnail((max_edge, max_edge), Image.LANCZOS)
        clean = Image.new("RGB", im.size)
        clean.putdata(list(im.getdata()))        # pixels only — no info dict, no EXIF
        clean.save(dest, "JPEG", quality=quality, optimize=True)
    return dest.stat().st_size


def synthetic_views(out: Path, count: int, size: int) -> None:
    """Draw a coloured hexagonal prism from `count` angles — obviously fake, exercises the UI."""
    for i in range(count):
        angle = 2 * math.pi * i / count
        im = Image.new("RGB", (size, size), (235, 235, 235))
        d = ImageDraw.Draw(im)
        cx, cy, r = size / 2, size / 2, size * 0.3
        pts = [
            (
                cx + r * math.cos(angle + k * math.pi / 3),
                cy + r * 0.5 * math.sin(angle + k * math.pi / 3),
            )
            for k in range(6)
        ]
        top = [(x, y - size * 0.18) for x, y in pts]
        for k in range(6):
            shade = 120 + int(100 * (0.5 + 0.5 * math.cos(angle + k * math.pi / 3)))
            d.polygon([pts[k], pts[(k + 1) % 6], top[(k + 1) % 6], top[k]], fill=(shade, 90, 160))
        d.polygon(top, fill=(240, 200, 80))
        d.text((8, 8), f"synthetic view {i + 1}/{count}", fill=(60, 60, 60))
        im.save(out / f"{i + 1:04d}.jpg", "JPEG", quality=80)


def build_mesh() -> trimesh.Trimesh:
    """A vertex-coloured torus knot-ish object: unmistakably procedural, a few KB as GLB."""
    mesh = trimesh.creation.torus(
        major_radius=1.0, minor_radius=0.35, major_sections=48, minor_sections=18
    )
    v = mesh.vertices
    t = (v[:, 2] - v[:, 2].min()) / np.ptp(v[:, 2])
    u = (np.arctan2(v[:, 1], v[:, 0]) + math.pi) / (2 * math.pi)
    colors = np.stack([
        (255 * (0.5 + 0.5 * np.sin(2 * math.pi * u))).astype(np.uint8),
        (255 * t).astype(np.uint8),
        (255 * (0.5 + 0.5 * np.cos(2 * math.pi * u))).astype(np.uint8),
        np.full(len(v), 255, dtype=np.uint8),
    ], axis=1)
    mesh.visual.vertex_colors = colors
    return mesh


def render_preview(mesh: trimesh.Trimesh, dest: Path, size: int = 512) -> None:
    """Painter's-algorithm orthographic render with Pillow — no OpenGL needed."""
    rot = trimesh.transformations.euler_matrix(math.radians(-60), 0, math.radians(30))
    v = trimesh.transform_points(mesh.vertices, rot)
    faces = mesh.faces
    colors = mesh.visual.vertex_colors[:, :3]
    lo, hi = v[:, :2].min(axis=0), v[:, :2].max(axis=0)
    scale = (size * 0.8) / max(hi - lo)
    xy = (v[:, :2] - lo) * scale + size * 0.1
    xy[:, 1] = size - xy[:, 1]
    depth = v[faces].mean(axis=1)[:, 2]
    im = Image.new("RGB", (size, size), (28, 28, 32))
    d = ImageDraw.Draw(im)
    light = np.array([0.3, 0.5, 0.8])
    normals = mesh.face_normals @ rot[:3, :3].T
    for fi in np.argsort(depth):
        f = faces[fi]
        shade = 0.35 + 0.65 * max(0.0, float(normals[fi] @ light))
        c = tuple(int(x * shade) for x in colors[f].mean(axis=0))
        d.polygon([tuple(xy[i]) for i in f], fill=c)
    d.text((10, size - 22), "placeholder mesh — not reconstructed", fill=(200, 200, 200))
    im.save(dest, "PNG", optimize=True)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--photos", type=Path, help="folder of phone photos")
    src.add_argument("--synthetic", action="store_true", help="draw placeholder views instead")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--max-edge", type=int, default=640)
    ap.add_argument("--quality", type=int, default=75)
    ap.add_argument("--count", type=int, default=12, help="synthetic view count")
    ap.add_argument("--budget-bytes", type=int, default=2_000_000)
    args = ap.parse_args()

    images = args.out / "images"
    images.mkdir(parents=True, exist_ok=True)
    for old in images.glob("*"):
        old.unlink()

    if args.synthetic:
        synthetic_views(images, args.count, args.max_edge)
        n = args.count
    else:
        photos = sorted(p for p in args.photos.iterdir() if p.suffix.lower() in IMAGE_EXTS)
        if len(photos) < 5:
            print(f"need at least 5 photos, found {len(photos)} in {args.photos}", file=sys.stderr)
            return 1
        total = 0
        for i, p in enumerate(photos, start=1):
            total += write_photo(p, images / f"{i:04d}.jpg", args.max_edge, args.quality)
        n = len(photos)
        print(f"{n} photos → {total / 1e6:.2f} MB")
        if total > args.budget_bytes:
            budget_mb = args.budget_bytes / 1e6
            print(
                f"WARNING: over the {budget_mb:.1f} MB budget — lower --quality or --max-edge",
                file=sys.stderr,
            )

    mesh = build_mesh()
    mesh.export(args.out / "mesh.glb")
    render_preview(mesh, args.out / "preview.png")
    glb_kb = (args.out / "mesh.glb").stat().st_size // 1024
    print(f"wrote {n} images, mesh.glb ({glb_kb} KB), preview.png → {args.out}")
    print(
        "\nOne-time upload of the shared prod sample set (run it yourself with your admin profile):"
    )
    print(f"  aws s3 sync {images} s3://<audio-bucket>/samples/photogrammetry/images/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
