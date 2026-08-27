"""Handler walks the stages, writes outputs under the job's own prefix, and maps failures per spec §1."""
import math
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError
from PIL import Image

from gpu_worker.sqs import Interrupted
from handlers.photogrammetry import Deps, process_photogrammetry_job
from pipeline.colmap import SparseModel
from pipeline.runner import StageError

USER = "user-1"


class FakeRecon:
    """Records stage calls; `registered` drives the threshold; `fail_at` raises in that stage."""
    def __init__(self, work, registered=10, fail_at=None, interrupt_at=None):
        self.work, self.registered, self.fail_at, self.interrupt_at = work, registered, fail_at, interrupt_at
        self.calls = []

    def _step(self, name):
        self.calls.append(name)
        if name == self.interrupt_at: raise Interrupted()
        if name == self.fail_at: raise StageError("tool", f"{name} exploded")

    def sfm(self, images):
        self._step("sfm"); return SparseModel(self.work / "sparse" / "0", self.registered)
    def dense(self, images, model):
        self._step("dense"); d = self.work / "dense"; d.mkdir(parents=True, exist_ok=True); return d
    def mesh(self, dense, refine):
        self._step(("mesh", refine)); return dense / "m.ply"
    def texture(self, dense, ply):
        self._step("texture")
        Image.new("RGB", (2, 2)).save(dense / "tex.png")
        (dense / "scene_textured.mtl").write_text("newmtl m\nmap_Kd tex.png\n")
        obj = dense / "scene_textured.obj"
        obj.write_text("mtllib scene_textured.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 0 1\nusemtl m\nf 1/1 2/2 3/3\n")
        return obj


class FakeS3:
    def __init__(self, keys):
        self.keys, self.uploaded, self.downloaded = keys, [], []
    def list_keys(self, prefix): return [k for k in self.keys if k.startswith(prefix)]
    def download(self, key, dest):
        self.downloaded.append(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (800, 600)).save(dest)
    def upload_file(self, path, key, content_type): self.uploaded.append((key, content_type, Path(path).stat().st_size > 0))


class FailingDownloadS3(FakeS3):
    """download() raises a transient S3 ClientError (M15)."""
    def download(self, key, dest):
        raise ClientError({"Error": {"Code": "SlowDown", "Message": "x"}}, "GetObject")


def make(tmp_path, *, status="queued", image_count=10, keys=None, recon_kwargs=None, s3_cls=FakeS3,
         include_placeholder=False):
    job_id = uuid.uuid4()
    prefix = f"photogrammetry/{USER}/{job_id}/input/"
    keys = keys if keys is not None else [f"{prefix}{i:04d}.jpg" for i in range(1, image_count + 1)]
    if include_placeholder:
        keys = [prefix] + keys
    job = MagicMock(id=job_id, user_id=USER, status=status, stage=None, image_count=image_count,
                    input_prefix=prefix, mesh_s3_key=None, preview_s3_key=None, error_message=None, completed_at=None)
    session = MagicMock()
    session.get.return_value = job

    @contextmanager
    def factory():
        yield session

    recons = []
    def recon_factory(work, deadline):
        r = FakeRecon(work, **(recon_kwargs or {})); recons.append(r); return r

    s3 = s3_cls(keys)
    deps = Deps(session_factory=factory, s3=s3, reconstruction_factory=recon_factory,
                work_root=tmp_path / "work", use_gpu=False, job_timeout_seconds=3600)
    return job, s3, recons, deps


def test_happy_path_walks_stages_and_writes_outputs_under_job_prefix(tmp_path):
    job, s3, recons, deps = make(tmp_path)
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert recons[0].calls == ["sfm", "dense", ("mesh", True), "texture"]
    assert job.status == "complete" and job.stage is None and isinstance(job.completed_at, datetime)
    assert job.mesh_s3_key == f"photogrammetry/{USER}/{job.id}/output/mesh.glb"
    assert job.preview_s3_key == f"photogrammetry/{USER}/{job.id}/output/preview.png"
    assert sorted(k for k, _, ok in s3.uploaded if ok) == [job.mesh_s3_key, job.preview_s3_key]
    assert dict((k, ct) for k, ct, _ in s3.uploaded)[job.mesh_s3_key] == "model/gltf-binary"
    assert not (tmp_path / "work" / str(job.id)).exists()   # scratch removed


def test_sample_job_outputs_go_under_job_prefix_not_input_prefix(tmp_path):
    job, s3, _, deps = make(tmp_path, keys=[f"samples/photogrammetry/images/{i:04d}.jpg" for i in range(1, 11)])
    job.input_prefix = "samples/photogrammetry/images/"
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert job.mesh_s3_key.startswith(f"photogrammetry/{USER}/{job.id}/output/")


def test_stage_progression_is_written_before_each_stage(tmp_path):
    job, _, recons, deps = make(tmp_path)
    seen = []
    orig = FakeRecon._step
    FakeRecon._step = lambda self, name: (seen.append(job.stage), orig(self, name))
    try:
        process_photogrammetry_job({"job_id": str(job.id)}, deps)
    finally:
        FakeRecon._step = orig
    assert seen == ["sfm", "dense", "mesh", "texture"]


def test_refine_skipped_over_100_images(tmp_path):
    # registered must clear the 60% threshold (ceil(0.6*101)=61) so the job reaches the mesh stage
    job, _, recons, deps = make(tmp_path, image_count=101, recon_kwargs={"registered": 101})
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert ("mesh", False) in recons[0].calls


def test_registration_threshold_fails_job_with_message(tmp_path):
    job, _, recons, deps = make(tmp_path, image_count=10, recon_kwargs={"registered": 5})   # < ceil(6)
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert job.status == "failed" and job.error_message == "Only 5 of 10 photos could be matched — add overlap and try again"
    assert recons[0].calls == ["sfm"]


def test_threshold_boundary_passes_at_ceil(tmp_path):
    job, _, _, deps = make(tmp_path, image_count=10, recon_kwargs={"registered": 6})
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert job.status == "complete"


def test_missing_uploads_fail_before_any_stage(tmp_path):
    job, _, recons, deps = make(tmp_path, image_count=10, keys=[])
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert job.status == "failed" and job.error_message == "0 of 10 photos found in storage"
    assert recons == []


def test_stage_error_marks_failed_and_returns_normally(tmp_path):
    job, _, _, deps = make(tmp_path, recon_kwargs={"fail_at": "dense"})
    process_photogrammetry_job({"job_id": str(job.id)}, deps)     # no raise → message acked
    assert job.status == "failed" and job.error_message == "dense exploded" and job.stage is None


def test_interrupt_resets_to_queued_and_raises(tmp_path):
    job, _, _, deps = make(tmp_path, recon_kwargs={"interrupt_at": "dense"})
    with pytest.raises(Interrupted):
        process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert job.status == "queued" and job.stage is None
    assert not (tmp_path / "work" / str(job.id)).exists()


def test_redelivered_terminal_job_is_skipped(tmp_path):
    job, _, recons, deps = make(tmp_path, status="complete")
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert recons == [] and job.status == "complete"


def test_processing_job_is_restarted(tmp_path):
    job, _, recons, deps = make(tmp_path, status="processing")
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert recons and job.status == "complete"


def test_unknown_job_is_skipped(tmp_path):
    job, _, recons, deps = make(tmp_path)
    with deps.session_factory() as sess:
        sess.get.return_value = None
    process_photogrammetry_job({"job_id": str(uuid.uuid4())}, deps)
    assert recons == []


def test_error_message_is_capped_at_1000_chars(tmp_path):
    job, _, _, deps = make(tmp_path, recon_kwargs={"fail_at": "sfm"})
    class LongRecon(FakeRecon):
        def sfm(self, images): raise StageError("tool", "x" * 5000)
    deps = Deps(session_factory=deps.session_factory, s3=deps.s3,
                reconstruction_factory=lambda work, deadline: LongRecon(work),
                work_root=deps.work_root, use_gpu=False, job_timeout_seconds=3600)
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert len(job.error_message) == 1000


def test_directory_placeholder_key_is_ignored_and_never_downloaded(tmp_path):
    """M11: S3 "folders" show up in list_keys as a zero-byte object ending in "/"."""
    job, s3, recons, deps = make(tmp_path, image_count=10, include_placeholder=True)
    process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert job.status == "complete"
    assert job.input_prefix not in s3.downloaded
    assert len(s3.downloaded) == 10


def test_transient_s3_error_during_download_leaves_job_processing_for_redelivery(tmp_path):
    """M15: a ClientError/BotoCoreError while listing or downloading must not be swallowed by
    the generic except Exception (which would fail the job); it re-raises so SQS redelivers,
    and the row is left `processing` so the load step restarts it."""
    job, s3, recons, deps = make(tmp_path, s3_cls=FailingDownloadS3)
    with pytest.raises(ClientError):
        process_photogrammetry_job({"job_id": str(job.id)}, deps)
    assert job.status == "processing"
    assert recons == []
    assert not (tmp_path / "work" / str(job.id)).exists()   # scratch still removed
