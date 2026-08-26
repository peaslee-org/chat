"""PhotogrammetryJob model shape and default settings."""
from sqlalchemy import Enum as SAEnum

from app.config import Settings
from app.models.base import Base


def test_photogrammetry_jobs_table_is_registered():
    import app.models  # noqa: F401  (imports every model module)
    table = Base.metadata.tables["photogrammetry_jobs"]
    cols = set(table.columns.keys())
    assert {
        "id", "user_id", "name", "status", "stage", "image_count", "input_prefix",
        "mesh_s3_key", "preview_s3_key", "error_message",
        "created_at", "updated_at", "completed_at",
    } <= cols
    status = table.columns["status"].type
    assert isinstance(status, SAEnum)
    assert set(status.enums) == {"pending", "queued", "processing", "complete", "failed"}
    assert status.name == "photogrammetry_job_status"


def test_photogrammetry_settings_defaults():
    s = Settings(_env_file=None)
    assert s.use_mock_photogrammetry is False
    assert s.mock_photogrammetry_stage_delay_seconds == 2.0
    assert s.photogrammetry_max_images == 150
    assert s.photogrammetry_sample_prefix == "samples/photogrammetry/"
    assert s.gpu_photogrammetry_task_family == ""
