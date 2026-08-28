"""Reconstruction is the stage table's view of colmap+openmvs: one method per tool group."""
from pipeline.reconstruct import Reconstruction

SAVED = "Mesh 'x.ply' saved: 3 vertices, 1 faces (0ms)\n"


class Runner:
    def __init__(self): self.cmds = []
    def run(self, cmd, cwd, tool=None):
        self.cmds.append(cmd); return SAVED


def test_mesh_stages_are_separate_calls(tmp_path):
    r = Runner()
    recon = Reconstruction(r, tmp_path, use_gpu=False)
    dense = tmp_path / "dense"
    ply, faces = recon.reconstruct_mesh(dense)
    assert ply == dense / "scene_dense_mesh.ply" and faces == 1
    refined, faces2 = recon.refine_mesh(dense, ply)
    assert refined == dense / "scene_dense_mesh_refine.ply" and faces2 == 1
    obj = recon.texture(dense, refined, decimate=0.5)
    assert obj == dense / "scene_textured.obj"
    assert [c[0] for c in r.cmds] == ["ReconstructMesh", "RefineMesh", "TextureMesh"]
    assert "--decimate" in r.cmds[2] and not hasattr(recon, "mesh")
