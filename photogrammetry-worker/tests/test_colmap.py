import pytest
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
    assert "--FeatureExtraction.use_gpu" in r.cmds[0] and r.cmds[0][r.cmds[0].index("--FeatureExtraction.use_gpu") + 1] == "0"
    assert "--FeatureMatching.use_gpu" in r.cmds[1] and r.cmds[1][r.cmds[1].index("--FeatureMatching.use_gpu") + 1] == "0"
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


class _MapperFails:
    def __init__(self, output): self.output = output
    def run(self, cmd, cwd, tool=None):
        from pipeline.runner import StageError
        if cmd[1] == "mapper":
            raise StageError("colmap mapper", "Failed to create any sparse model", self.output)
        return ""


def test_mapper_no_initial_pair_means_zero_registered(tmp_path):
    # COLMAP 4.x exits 1 with no initial pair (5 identical photos, acceptance 7.3): the 60 % gate,
    # not the raw glog line, must be what the user sees.
    m = sparse_reconstruct(_MapperFails("E... sfm.cc:288] Failed to create any sparse model\n"), tmp_path, tmp_path / "images", True)
    assert m.registered_images == 0


def test_other_mapper_failures_propagate(tmp_path):
    from pipeline.runner import StageError
    with pytest.raises(StageError):
        sparse_reconstruct(_MapperFails("E... something else broke\n"), tmp_path, tmp_path / "images", True)


# ── registered image names (which photos the model actually used) ────────────
import struct

from pipeline.colmap import registered_image_names


def write_images_bin(path, names, points2d=(0, 2)):
    """Minimal COLMAP images.bin: per image id, qvec, tvec, camera_id, name\\0, points2D."""
    buf = bytearray(struct.pack("<Q", len(names)))
    for i, name in enumerate(names, start=1):
        buf += struct.pack("<i", i) + struct.pack("<4d", 1, 0, 0, 0) + struct.pack("<3d", 0, 0, 0)
        buf += struct.pack("<i", 1) + name.encode() + b"\0"
        n = points2d[i % len(points2d)]
        buf += struct.pack("<Q", n) + b"".join(struct.pack("<ddq", 1.0, 2.0, -1) for _ in range(n))
    path.write_bytes(bytes(buf))


def test_registered_image_names_from_images_bin(tmp_path):
    write_images_bin(tmp_path / "images.bin", ["0003.jpg", "0001.jpg", "0007.jpg"])
    assert registered_image_names(tmp_path) == {"0001.jpg", "0003.jpg", "0007.jpg"}


def test_registered_image_names_from_images_txt(tmp_path):
    (tmp_path / "images.txt").write_text(
        "# Image list with two lines of data per image:\n"
        "#   IMAGE_ID, QW, QX, QY, QZ, TX, TY, TZ, CAMERA_ID, NAME\n"
        "1 1 0 0 0 0 0 0 1 0002.jpg\n"
        "10.5 20.5 -1 30 40 7\n"
        "2 1 0 0 0 0 0 0 1 0005.jpg\n"
        "\n"
    )
    assert registered_image_names(tmp_path) == {"0002.jpg", "0005.jpg"}


def test_registered_image_names_empty_without_model_files(tmp_path):
    assert registered_image_names(tmp_path) == set()
    assert registered_image_names(tmp_path / "nope") == set()


def test_sparse_reconstruct_carries_registered_names(tmp_path):
    work, images = tmp_path / "w", tmp_path / "i"
    make_sparse(work, ["0"])
    write_images_bin(work / "sparse" / "0" / "images.bin", ["0001.jpg", "0002.jpg"])
    model = sparse_reconstruct(FakeRunner({"0": 2}), work, images, use_gpu=False)
    assert model.registered_images == 2
    assert model.registered_names == frozenset({"0001.jpg", "0002.jpg"})
