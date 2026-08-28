"""Marker files that let a restarted job skip finished stages and refuse to repeat a crashed one."""
import json
import os
import time

from pipeline.checkpoints import STAGES, Checkpoints, sweep_stale


def test_done_records_data_and_clears_started(tmp_path):
    ck = Checkpoints(tmp_path)
    ck.started("sfm")
    assert (tmp_path / "stage.started").read_text() == "sfm"
    ck.done("sfm", sparse="/w/sparse/0", registered_images=42)
    assert ck.completed("sfm") == {"sparse": "/w/sparse/0", "registered_images": 42}
    assert not (tmp_path / "stage.started").exists() and ck.crashed_stage() is None


def test_started_without_done_is_a_crash(tmp_path):
    ck = Checkpoints(tmp_path)
    ck.done("sfm", sparse="s", registered_images=1)
    ck.started("dense")
    assert ck.crashed_stage() == "dense"
    assert ck.completed("dense") is None


def test_clear_started_is_the_interrupted_path(tmp_path):
    ck = Checkpoints(tmp_path)
    ck.started("mesh"); ck.clear_started()
    assert ck.crashed_stage() is None and not (tmp_path / "stage.started").exists()


def test_first_incomplete_walks_stage_order(tmp_path):
    ck = Checkpoints(tmp_path)
    assert ck.first_incomplete() == "sfm"
    ck.done("sfm"); ck.done("dense")
    assert ck.first_incomplete() == "mesh"
    for s in STAGES: ck.done(s)
    assert ck.first_incomplete() == "publish"   # publish.done is never written in practice; last stage wins


def test_missing_work_dir_is_fresh(tmp_path):
    ck = Checkpoints(tmp_path / "nope")
    assert ck.crashed_stage() is None and ck.completed("sfm") is None and ck.first_incomplete() == "sfm"


def test_sweep_stale_removes_old_job_dirs_only(tmp_path):
    old, new = tmp_path / "old-job", tmp_path / "new-job"
    old.mkdir(); (old / "sfm.done").write_text("{}"); new.mkdir(); (new / "x").write_text("y")
    (tmp_path / "loose-file").write_text("ignored")
    stale = time.time() - 2 * 86_400
    os.utime(old, (stale, stale)); os.utime(old / "sfm.done", (stale, stale))
    removed = sweep_stale(tmp_path, max_age_seconds=86_400)
    assert removed == [old] and not old.exists() and new.exists() and (tmp_path / "loose-file").exists()


def test_corrupt_done_marker_counts_as_not_done(tmp_path):
    ck = Checkpoints(tmp_path)
    (tmp_path / "sfm.done").write_text("{not json")
    assert ck.completed("sfm") is None
    assert ck.first_incomplete() == "sfm"
    ck.started("sfm")
    assert ck.crashed_stage() == "sfm"   # a corrupt .done does not hide a crash


def test_empty_started_marker_is_not_a_crash(tmp_path):
    ck = Checkpoints(tmp_path)
    (tmp_path / "stage.started").write_text("")
    assert ck.crashed_stage() is None


def test_markers_are_written_atomically(tmp_path):
    ck = Checkpoints(tmp_path)
    ck.started("dense")
    ck.done("dense", dense="d")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["dense.done"]   # no .tmp left behind
