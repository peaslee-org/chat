from unittest.mock import MagicMock, patch

from app.services.audio_storage import (
    AudioStorageService,
    LocalAudioStorageService,
    MockAudioStorageService,
)


def test_local_download_url_points_at_sink(tmp_path):
    s = LocalAudioStorageService("http://localhost:8000/", str(tmp_path))
    assert (
        s.generate_presigned_download_url("photogrammetry/u/j/output/mesh.glb")
        == "http://localhost:8000/api/v1/transcribe/dev-upload/photogrammetry/u/j/output/mesh.glb"
    )


def test_local_write_object_creates_parents_and_is_visible(tmp_path):
    s = LocalAudioStorageService("http://localhost:8000", str(tmp_path))
    s.write_object("a/b/c.bin", b"xyz")
    assert (tmp_path / "a" / "b" / "c.bin").read_bytes() == b"xyz"
    assert s.object_exists("a/b/c.bin")
    assert s.list_keys_with_prefix("a/b/") == ["a/b/c.bin"]


def test_mock_download_url_and_write_object():
    s = MockAudioStorageService("http://localhost:8000")
    assert s.generate_presigned_download_url("k") == "http://localhost:8000/api/v1/transcribe/dev-upload/k"
    # dev implementations accept the attachment kwarg and ignore it
    url = s.generate_presigned_download_url("k", attachment_filename="x.glb")
    assert url.endswith("/dev-upload/k")
    s.write_object("k", b"")  # no-op, must not raise


def test_real_download_url_uses_get_object():
    with patch("app.services.audio_storage.boto3"):
        settings = MagicMock(aws_region="us-east-1", audio_bucket_name="bucket")
        s = AudioStorageService(settings)
        s.s3.generate_presigned_url = MagicMock(return_value="https://signed")
        assert s.generate_presigned_download_url("k", ttl_seconds=60) == "https://signed"
        s.s3.generate_presigned_url.assert_called_once_with(
            "get_object", Params={"Bucket": "bucket", "Key": "k"}, ExpiresIn=60
        )


def test_real_download_url_with_attachment_filename_sets_content_disposition():
    with patch("app.services.audio_storage.boto3"):
        settings = MagicMock(aws_region="us-east-1", audio_bucket_name="bucket")
        s = AudioStorageService(settings)
        s.s3.generate_presigned_url = MagicMock(return_value="https://signed")
        url = s.generate_presigned_download_url("k", ttl_seconds=60, attachment_filename="scan.glb")
        assert url == "https://signed"
        s.s3.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={
                "Bucket": "bucket",
                "Key": "k",
                "ResponseContentDisposition": 'attachment; filename="scan.glb"',
            },
            ExpiresIn=60,
        )


def test_local_download_url_accepts_attachment_filename(tmp_path):
    s = LocalAudioStorageService("http://localhost:8000", str(tmp_path))
    url = s.generate_presigned_download_url("k", attachment_filename="x.glb")
    assert url.endswith("/dev-upload/k")


def test_real_write_object_uses_put_object_with_content_type():
    with patch("app.services.audio_storage.boto3"):
        settings = MagicMock(aws_region="us-east-1", audio_bucket_name="bucket")
        s = AudioStorageService(settings)
        s.write_object("p/thumbs/0001.jpg", b"\xff\xd8", content_type="image/jpeg")
        s.s3.put_object.assert_called_once_with(
            Bucket="bucket", Key="p/thumbs/0001.jpg", Body=b"\xff\xd8", ContentType="image/jpeg"
        )
