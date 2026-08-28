"""OpenMVS wrapper: each step names its tool, runs in the dense workspace, returns the next file."""
from pipeline.openmvs import densify, interface, reconstruct_mesh, refine_mesh, texture_mesh, mesh_faces
from pipeline.runner import StageError
import pytest

SAVED = "19:05:16 [Mesh    ] Mesh 'scene_dense_mesh.ply' saved: 337881 vertices, 675489 faces (72ms)\n19:05:16 [App     ] \tVmPeak:\t 6302564 kB\n"


class FakeRunner:
    def __init__(self): self.calls = []
    def run(self, cmd, cwd, tool=None):
        self.calls.append((cmd, cwd, tool)); return ""


class OutputRunner(FakeRunner):
    def __init__(self, output=SAVED):
        super().__init__(); self.output = output
    def run(self, cmd, cwd, tool=None):
        super().run(cmd, cwd, tool); return self.output


def test_chain_produces_expected_paths(tmp_path):
    r = OutputRunner()
    dense = tmp_path / "dense"
    scene = interface(r, dense)
    scene_dense = densify(r, dense, scene)
    mesh, _ = reconstruct_mesh(r, dense, scene_dense)
    refined, _ = refine_mesh(r, dense, scene_dense, mesh)
    obj = texture_mesh(r, dense, scene_dense, refined)
    assert [c[0][0] for c in r.calls] == ["InterfaceCOLMAP", "DensifyPointCloud", "ReconstructMesh", "RefineMesh", "TextureMesh"]
    assert all(c[1] == dense for c in r.calls)
    assert [c[2] for c in r.calls] == ["InterfaceCOLMAP", "DensifyPointCloud", "ReconstructMesh", "RefineMesh", "TextureMesh"]
    assert scene == dense / "scene.mvs" and scene_dense == dense / "scene_dense.mvs"
    assert mesh == dense / "scene_dense_mesh.ply" and refined == dense / "scene_dense_mesh_refine.ply"
    assert obj == dense / "scene_textured.obj"


def test_densify_uses_resolution_level_2(tmp_path):
    r = FakeRunner()
    densify(r, tmp_path, tmp_path / "scene.mvs")
    cmd = r.calls[0][0]
    assert cmd[cmd.index("--resolution-level") + 1] == "2"


def test_densify_cuda_device_follows_use_gpu(tmp_path):
    for use_gpu, expected in ((True, "-1"), (False, "-2")):
        r = FakeRunner()
        densify(r, tmp_path, tmp_path / "scene.mvs", use_gpu)
        cmd = r.calls[0][0]
        assert cmd[cmd.index("--cuda-device") + 1] == expected


def test_every_openmvs_tool_gets_cuda_device(tmp_path):
    # Densify/ReconstructMesh/TextureMesh default to -1 and init CUDA at startup; RefineMesh to -2.
    for use_gpu, expected in ((True, "-1"), (False, "-2")):
        r = OutputRunner()
        reconstruct_mesh(r, tmp_path, tmp_path / "scene_dense.mvs", use_gpu)
        texture_mesh(r, tmp_path, tmp_path / "scene_dense.mvs", tmp_path / "mesh.ply", use_gpu)
        for cmd, _cwd, _tool in r.calls:
            assert cmd[cmd.index("--cuda-device") + 1] == expected, cmd[0]


def test_refine_mesh_cuda_device_is_explicit(tmp_path):
    # RefineMesh defaults to CPU (-2) upstream; the GPU host must ask for -1.
    for use_gpu, expected in ((True, "-1"), (False, "-2")):
        r = OutputRunner()
        refine_mesh(r, tmp_path, tmp_path / "scene_dense.mvs", tmp_path / "mesh.ply", use_gpu)
        cmd = r.calls[0][0]
        assert cmd[cmd.index("--cuda-device") + 1] == expected


def test_texture_exports_obj(tmp_path):
    r = FakeRunner()
    texture_mesh(r, tmp_path, tmp_path / "scene_dense.mvs", tmp_path / "m.ply")
    cmd = r.calls[0][0]
    assert cmd[cmd.index("--export-type") + 1] == "obj"


def test_texture_mesh_disables_seam_leveling(tmp_path):
    """Both seam-leveling passes in our OpenMVS v2.4.0/noble build write ~0 into every face
    pixel (atlas = black faces, coloured surroundings; found 2026-08-28 on the sample scan).
    With both off the raw patch copy is correct. Keep them off until the build is fixed."""
    r = FakeRunner()
    texture_mesh(r, tmp_path, tmp_path / "scene_dense.mvs", tmp_path / "mesh.ply")
    cmd = r.calls[0][0]
    assert cmd[cmd.index("--global-seam-leveling") + 1] == "0"
    assert cmd[cmd.index("--local-seam-leveling") + 1] == "0"


def test_mesh_faces_reads_last_saved_line():
    two = "Mesh 'a.ply' saved: 10 vertices, 20 faces (1ms)\nMesh 'b.ply' saved: 30 vertices, 40 faces (1ms)\n"
    assert mesh_faces(two) == 40


def test_mesh_faces_raises_when_absent():
    with pytest.raises(StageError) as e:
        mesh_faces("no mesh here", tool="ReconstructMesh")
    assert e.value.tool == "ReconstructMesh" and "face count" in str(e.value)


def test_reconstruct_and_refine_return_face_counts(tmp_path):
    r = OutputRunner()
    ply, faces = reconstruct_mesh(r, tmp_path, tmp_path / "scene_dense.mvs")
    assert ply == tmp_path / "scene_dense_mesh.ply" and faces == 675489
    ply2, faces2 = refine_mesh(r, tmp_path, tmp_path / "scene_dense.mvs", ply)
    assert ply2 == tmp_path / "scene_dense_mesh_refine.ply" and faces2 == 675489


def test_texture_mesh_passes_decimate_only_when_given(tmp_path):
    r = FakeRunner()
    texture_mesh(r, tmp_path, tmp_path / "s.mvs", tmp_path / "m.ply")
    assert "--decimate" not in r.calls[0][0]
    texture_mesh(r, tmp_path, tmp_path / "s.mvs", tmp_path / "m.ply", decimate=0.396)
    cmd = r.calls[1][0]
    assert cmd[cmd.index("--decimate") + 1] == "0.396"
