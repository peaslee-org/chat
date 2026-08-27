"""COLMAP wrapper: command shape, model selection by registered images, GPU flag."""
from pathlib import Path

from pipeline.colmap import SparseModel, sparse_reconstruct, undistort


class FakeRunner:
    """Records commands; `model_analyzer` output comes from `analyses` keyed by model dir name.

    This text stands in for `Runner.run`'s combined stdout+stderr output — real COLMAP
    (glog) writes the `Registered images:` line to stderr, which `Runner.run` merges in.
    """
    def __init__(self, analyses):
        self.cmds = []
        self.calls = []
        self.analyses = analyses

    def run(self, cmd, cwd, tool=None):
        self.cmds.append(cmd)
        self.calls.append((cmd, cwd, tool))
        if cmd[1] == "model_analyzer":
            name = Path(cmd[cmd.index("--path") + 1]).name
            return f"Cameras: 1\nImages: 22\nRegistered images: {self.analyses[name]}\nPoints: 100\n"
        return ""


class FakeRunnerStderrLine(FakeRunner):
    """As FakeRunner, but shaped like real COLMAP: the `Registered images:` line is
    written to stderr and only present because `Runner.run` merges stdout + stderr into
    one string. Proves `sparse_reconstruct` doesn't assume the count is on stdout."""

    def run(self, cmd, cwd, tool=None):
        self.cmds.append(cmd)
        self.calls.append((cmd, cwd, tool))
        if cmd[1] == "model_analyzer":
            name = Path(cmd[cmd.index("--path") + 1]).name
            # stdout would be "" here; this is what real COLMAP puts on stderr, and
            # Runner.run hands back stdout + stderr concatenated.
            return "\n" + f"Cameras: 1\nImages: 22\nRegistered images: {self.analyses[name]}\nPoints: 100\n"
        return ""


def make_sparse(work, names):
    for n in names:
        (work / "sparse" / n).mkdir(parents=True)


def test_sparse_reconstruct_runs_extract_match_map_with_gpu_flags(tmp_path):
    make_sparse(tmp_path, ["0"])
    r = FakeRunner({"0": 20})
    model = sparse_reconstruct(r, tmp_path, tmp_path / "images", use_gpu=False)
    subcommands = [c[1] for c in r.cmds]
    assert subcommands[:3] == ["feature_extractor", "exhaustive_matcher", "mapper"]
    assert "--SiftExtraction.use_gpu" in r.cmds[0] and r.cmds[0][r.cmds[0].index("--SiftExtraction.use_gpu") + 1] == "0"
    assert "--SiftMatching.use_gpu" in r.cmds[1] and r.cmds[1][r.cmds[1].index("--SiftMatching.use_gpu") + 1] == "0"
    assert "--ImageReader.single_camera" in r.cmds[0]
    assert model == SparseModel(path=tmp_path / "sparse" / "0", registered_images=20)
    assert all(c[1] == tmp_path for c in r.calls)
    assert [c[2] for c in r.calls] == [
        "colmap feature_extractor",
        "colmap exhaustive_matcher",
        "colmap mapper",
        "colmap model_analyzer",
    ]


def test_picks_model_with_most_registered_images(tmp_path):
    make_sparse(tmp_path, ["0", "1", "2"])
    r = FakeRunner({"0": 5, "1": 17, "2": 9})
    model = sparse_reconstruct(r, tmp_path, tmp_path / "images", use_gpu=True)
    assert model.path.name == "1" and model.registered_images == 17


def test_tie_keeps_first_in_sorted_order(tmp_path):
    make_sparse(tmp_path, ["0", "1"])
    r = FakeRunner({"0": 9, "1": 9})
    model = sparse_reconstruct(r, tmp_path, tmp_path / "images", use_gpu=True)
    assert model.path.name == "0" and model.registered_images == 9


def test_no_model_means_zero_registered(tmp_path):
    (tmp_path / "sparse").mkdir()
    r = FakeRunner({})
    model = sparse_reconstruct(r, tmp_path, tmp_path / "images", use_gpu=True)
    assert model.registered_images == 0
    assert model.path == tmp_path / "sparse" / "0"


def test_registered_images_found_when_only_on_stderr(tmp_path):
    make_sparse(tmp_path, ["0"])
    r = FakeRunnerStderrLine({"0": 20})
    model = sparse_reconstruct(r, tmp_path, tmp_path / "images", use_gpu=False)
    assert model == SparseModel(path=tmp_path / "sparse" / "0", registered_images=20)


def test_undistort_writes_dense_workspace(tmp_path):
    r = FakeRunner({})
    dense = undistort(r, tmp_path, tmp_path / "images", SparseModel(tmp_path / "sparse" / "0", 10))
    cmd = r.cmds[0]
    assert cmd[1] == "image_undistorter" and dense == tmp_path / "dense"
    assert cmd[cmd.index("--output_type") + 1] == "COLMAP"
    assert r.calls[0][1] == tmp_path and r.calls[0][2] == "colmap image_undistorter"
