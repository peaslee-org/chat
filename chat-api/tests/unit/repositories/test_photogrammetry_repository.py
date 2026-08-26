"""PhotogrammetryRepository — statement shape / mutation verified against a mocked AsyncSession."""
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.repositories.photogrammetry import PhotogrammetryRepository


def make_repo(scalar=0, one_or_none=None):
    db = MagicMock()
    result = MagicMock()
    result.scalar_one = MagicMock(return_value=scalar)
    result.scalar_one_or_none = MagicMock(return_value=one_or_none)
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.delete = AsyncMock()
    return PhotogrammetryRepository(db), db


def compiled(db) -> str:
    stmt = db.execute.await_args.args[0]
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


async def test_create_job_uses_given_id_and_pending_status():
    repo, db = make_repo()
    job_id = uuid4()
    job = await repo.create_job(job_id, "user1", "Scan", 12, f"photogrammetry/user1/{job_id}/input/")
    assert job.id == job_id
    assert job.status == "pending"
    assert job.image_count == 12
    db.add.assert_called_once_with(job)
    db.flush.assert_awaited_once()


async def test_count_active_jobs_counts_pending_queued_processing():
    repo, db = make_repo(scalar=2)
    assert await repo.count_active_jobs("user1") == 2
    sql = compiled(db)
    assert "photogrammetry_jobs" in sql
    for s in ("pending", "queued", "processing"):
        assert f"'{s}'" in sql
    assert "'complete'" not in sql


async def test_update_job_status_sets_stage_keys_and_completed_at():
    job = MagicMock()
    job.completed_at = None
    repo, db = make_repo(one_or_none=job)
    await repo.update_job_status(uuid4(), "processing", stage="dense")
    assert job.status == "processing"
    assert job.stage == "dense"
    assert job.completed_at is None

    await repo.update_job_status(uuid4(), "complete", mesh_s3_key="k/mesh.glb", preview_s3_key="k/preview.png")
    assert job.status == "complete"
    assert job.stage is None
    assert job.mesh_s3_key == "k/mesh.glb"
    assert job.preview_s3_key == "k/preview.png"
    assert job.completed_at is not None


async def test_get_job_scopes_by_user():
    repo, db = make_repo(one_or_none=None)
    assert await repo.get_job(uuid4(), "user1") is None
    sql = compiled(db)
    assert "user_id = 'user1'" in sql
