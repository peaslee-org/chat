"""COLMAP: sparse reconstruction (the `sfm` stage) and undistortion for OpenMVS."""
import re
from dataclasses import dataclass
from pathlib import Path

from pipeline.runner import StageError

_NO_MODEL = "Failed to create any sparse model"
_REGISTERED = re.compile(r"Registered images:\s*(\d+)")


@dataclass(frozen=True)
class SparseModel:
    path: Path
    registered_images: int


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
    return best


def undistort(runner, work: Path, images: Path, model: SparseModel) -> Path:
    dense = work / "dense"
    runner.run([
        "colmap", "image_undistorter", "--image_path", str(images), "--input_path", str(model.path),
        "--output_path", str(dense), "--output_type", "COLMAP",
    ], cwd=work, tool="colmap image_undistorter")
    return dense
