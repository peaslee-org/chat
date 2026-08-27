"""OpenMVS wrapper: each step names its tool, runs in the dense workspace, returns the next file."""
from pipeline.openmvs import densify, interface, reconstruct_mesh, refine_mesh, texture_mesh


class FakeRunner:
    def __init__(self): self.calls = []
    def run(self, cmd, cwd, tool=None):
        self.calls.append((cmd, cwd, tool)); return ""


def test_chain_produces_expected_paths(tmp_path):
    r = FakeRunner()
    dense = tmp_path / "dense"
    scene = interface(r, dense)
    scene_dense = densify(r, dense, scene)
    mesh = reconstruct_mesh(r, dense, scene_dense)
    refined = refine_mesh(r, dense, scene_dense, mesh)
    obj = texture_mesh(r, dense, scene_dense, refined)
    assert [c[0][0] for c in r.calls] == ["InterfaceCOLMAP", "DensifyPointCloud", "ReconstructMesh", "RefineMesh", "TextureMesh"]
    assert all(c[1] == dense for c in r.calls)
    assert scene == dense / "scene.mvs" and scene_dense == dense / "scene_dense.mvs"
    assert mesh == dense / "scene_dense_mesh.ply" and refined == dense / "scene_dense_mesh_refine.ply"
    assert obj == dense / "scene_textured.obj"


def test_densify_uses_resolution_level_2(tmp_path):
    r = FakeRunner()
    densify(r, tmp_path, tmp_path / "scene.mvs")
    cmd = r.calls[0][0]
    assert cmd[cmd.index("--resolution-level") + 1] == "2"


def test_texture_exports_obj(tmp_path):
    r = FakeRunner()
    texture_mesh(r, tmp_path, tmp_path / "scene_dense.mvs", tmp_path / "m.ply")
    cmd = r.calls[0][0]
    assert cmd[cmd.index("--export-type") + 1] == "obj"
