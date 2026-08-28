"""OpenMVS: dense → mesh → (refine) → texture. Every step runs inside the COLMAP dense workspace."""
from pathlib import Path


def interface(runner, dense: Path) -> Path:
    out = dense / "scene.mvs"
    runner.run(["InterfaceCOLMAP", "-i", str(dense), "-o", str(out), "-w", str(dense)], cwd=dense, tool="InterfaceCOLMAP")
    return out


def _cuda_device(use_gpu: bool) -> list[str]:
    """OpenMVS: -1 = best GPU, -2 = CPU. Passed to all four tools: three default to -1 and
    initialise CUDA at startup (a crash without a usable driver), RefineMesh defaults to -2."""
    return ["--cuda-device", "-1" if use_gpu else "-2"]


def densify(runner, dense: Path, scene: Path, use_gpu: bool = True) -> Path:
    out = dense / "scene_dense.mvs"
    runner.run(["DensifyPointCloud", str(scene), "-w", str(dense), "-o", str(out), "--resolution-level", "2",
                *_cuda_device(use_gpu)], cwd=dense, tool="DensifyPointCloud")
    return out


def reconstruct_mesh(runner, dense: Path, scene_dense: Path, use_gpu: bool = True) -> Path:
    out = dense / "scene_dense_mesh.mvs"
    runner.run(["ReconstructMesh", str(scene_dense), "-w", str(dense), "-o", str(out), *_cuda_device(use_gpu)],
               cwd=dense, tool="ReconstructMesh")
    return dense / "scene_dense_mesh.ply"


def refine_mesh(runner, dense: Path, scene_dense: Path, mesh_ply: Path, use_gpu: bool = True) -> Path:
    out = dense / "scene_dense_mesh_refine.mvs"
    runner.run(["RefineMesh", str(scene_dense), "-m", str(mesh_ply), "-w", str(dense), "-o", str(out),
                *_cuda_device(use_gpu)], cwd=dense, tool="RefineMesh")
    return dense / "scene_dense_mesh_refine.ply"


def texture_mesh(runner, dense: Path, scene_dense: Path, mesh_ply: Path, use_gpu: bool = True) -> Path:
    out = dense / "scene_textured.mvs"
    # Seam leveling is OFF on purpose: in our OpenMVS v2.4.0 build (Ubuntu noble, OpenCV 4.6) both
    # the global and the local pass rewrite every face's pixels as ~0 (faces render black with
    # stray saturated texels), while the raw patch copy is correct. Verified 2026-08-28 by
    # re-running TextureMesh on the sample scan with each option toggled. Visible patch seams are
    # the price until the build is root-caused (docs/TODO.md, "Worker image").
    runner.run(["TextureMesh", str(scene_dense), "-m", str(mesh_ply), "-w", str(dense), "-o", str(out),
                "--export-type", "obj", "--global-seam-leveling", "0", "--local-seam-leveling", "0",
                *_cuda_device(use_gpu)], cwd=dense, tool="TextureMesh")
    return dense / "scene_textured.obj"
