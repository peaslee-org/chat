"""Reconstruction stages: one method per tool group; the handler decides refine and decimation."""
from pathlib import Path

from pipeline import colmap, openmvs
from pipeline.colmap import SparseModel


class Reconstruction:
    def __init__(self, runner, work: Path, use_gpu: bool):
        self._r = runner
        self._work = work
        self._gpu = use_gpu

    def sfm(self, images: Path) -> SparseModel:
        return colmap.sparse_reconstruct(self._r, self._work, images, self._gpu)

    def dense(self, images: Path, model: SparseModel) -> Path:
        dense = colmap.undistort(self._r, self._work, images, model)
        scene = openmvs.interface(self._r, dense)
        openmvs.densify(self._r, dense, scene, self._gpu)
        return dense

    def reconstruct_mesh(self, dense: Path) -> tuple[Path, int]:
        return openmvs.reconstruct_mesh(self._r, dense, dense / "scene_dense.mvs", self._gpu)

    def refine_mesh(self, dense: Path, mesh_ply: Path) -> tuple[Path, int]:
        return openmvs.refine_mesh(self._r, dense, dense / "scene_dense.mvs", mesh_ply, self._gpu)

    def texture(self, dense: Path, mesh_ply: Path, decimate: float | None = None) -> Path:
        return openmvs.texture_mesh(self._r, dense, dense / "scene_dense.mvs", mesh_ply, self._gpu, decimate=decimate)
