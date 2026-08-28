"""The four stages as one object so the handler can be tested with a fake."""
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

    def mesh(self, dense: Path, refine: bool) -> Path:
        scene_dense = dense / "scene_dense.mvs"
        ply = openmvs.reconstruct_mesh(self._r, dense, scene_dense)
        if refine:
            ply = openmvs.refine_mesh(self._r, dense, scene_dense, ply, self._gpu)
        return ply

    def texture(self, dense: Path, mesh_ply: Path) -> Path:
        return openmvs.texture_mesh(self._r, dense, dense / "scene_dense.mvs", mesh_ply)
