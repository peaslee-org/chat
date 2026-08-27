import os
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/x")
os.environ.setdefault("AUDIO_BUCKET_NAME", "b")
os.environ.setdefault("PHOTOGRAMMETRY_SQS_QUEUE_URL", "https://sqs.test/q")

import main  # noqa: E402
from pipeline.reconstruct import Reconstruction  # noqa: E402


def test_handlers_and_deps_wiring(tmp_path):
    assert set(main.HANDLERS) == {"photogrammetry_job"}
    with patch("main.S3Client"), patch("main.make_session_factory"):
        deps = main.build_deps(main.settings)
    recon = deps.reconstruction_factory(tmp_path, 10.0)
    assert isinstance(recon, Reconstruction)
    assert deps.job_timeout_seconds == 3600 and deps.use_gpu is True
