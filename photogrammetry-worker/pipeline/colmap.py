"""COLMAP: sparse reconstruction (the `sfm` stage) and undistortion for OpenMVS."""
import re
import struct
from dataclasses import dataclass
from pathlib import Path

from pipeline.runner import StageError

_NO_MODEL = "Failed to create any sparse model"
_REGISTERED = re.compile(r"Registered images:\s*(\d+)")


@dataclass(frozen=True)
class SparseModel:
    path: Path
    registered_images: int
    registered_names: frozenset[str] = frozenset()   # input filenames the model actually used


def registered_image_names(model_dir: Path) -> set[str]:
    """Filenames of the images registered in a COLMAP model directory (images.bin, else
    images.txt). Empty when neither exists — e.g. when the mapper produced no model."""
    binary = model_dir / "images.bin"
    if binary.is_file():
        return _names_from_images_bin(binary.read_bytes())
    text = model_dir / "images.txt"
    if text.is_file():
        return _names_from_images_txt(text.read_text())
    return set()


def _names_from_images_bin(data: bytes) -> set[str]:
    # Layout per image: image_id int32, qvec 4×f64, tvec 3×f64, camera_id int32, NAME\0,
    # num_points2d uint64, then num_points2d × (x f64, y f64, point3d_id int64).
    names: set[str] = set()
    (count,) = struct.unpack_from("<Q", data, 0)
    off = 8
    for _ in range(count):
        off += 4 + 8 * 4 + 8 * 3 + 4
        end = data.index(b"\0", off)
        names.add(data[off:end].decode())
        off = end + 1
        (n_points,) = struct.unpack_from("<Q", data, off)
        off += 8 + n_points * (8 + 8 + 8)
    return names


def _names_from_images_txt(text: str) -> set[str]:
    # Two lines per image: the first has "IMAGE_ID QW QX QY QZ TX TY TZ CAMERA_ID NAME".
    names: set[str] = set()
    rows = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    for ln in rows[::2]:
        parts = ln.split()
        if len(parts) >= 10:
            names.add(parts[9])
    return names


def sparse_reconstruct(runner, work: Path, images: Path, use_gpu: bool) -> SparseModel:
    db = work / "database.db"
    sparse = work / "sparse"
    sparse.mkdir(parents=True, exist_ok=True)
    gpu = "1" if use_gpu else "0"
    runner.run([
        "colmap", "feature_extractor", "--database_path", str(db), "--image_path", str(images),
        "--ImageReader.camera_model", "SIMPLE_RADIAL", "--ImageReader.single_camera", "1",
        "--FeatureExtraction.use_gpu", gpu,
    ], cwd=work, tool="colmap feature_extractor")
    runner.run([
        "colmap", "exhaustive_matcher", "--database_path", str(db), "--FeatureMatching.use_gpu", gpu,
    ], cwd=work, tool="colmap exhaustive_matcher")
    try:
        runner.run([
            "colmap", "mapper", "--database_path", str(db), "--image_path", str(images), "--output_path", str(sparse),
        ], cwd=work, tool="colmap mapper")
    except StageError as e:
        # COLMAP 4.x exits 1 when no initial image pair exists (e.g. near-identical photos). That is
        # "nothing registered", and the caller's 60 % gate owns the user-facing message.
        if _NO_MODEL in e.output:
            return SparseModel(sparse / "0", 0)
        raise
    best = SparseModel(sparse / "0", 0)
    for model_dir in sorted(p for p in sparse.iterdir() if p.is_dir()):
        out = runner.run(["colmap", "model_analyzer", "--path", str(model_dir)], cwd=work, tool="colmap model_analyzer")
        m = _REGISTERED.search(out)
        n = int(m.group(1)) if m else 0
        if n > best.registered_images:
            best = SparseModel(model_dir, n)
    if best.registered_images:
        best = SparseModel(best.path, best.registered_images, frozenset(registered_image_names(best.path)))
    return best


def undistort(runner, work: Path, images: Path, model: SparseModel) -> Path:
    dense = work / "dense"
    runner.run([
        "colmap", "image_undistorter", "--image_path", str(images), "--input_path", str(model.path),
        "--output_path", str(dense), "--output_type", "COLMAP",
    ], cwd=work, tool="colmap image_undistorter")
    return dense
