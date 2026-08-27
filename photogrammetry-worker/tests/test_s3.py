from pathlib import Path
from unittest.mock import MagicMock

from services.s3 import S3Client


def make():
    client = MagicMock()
    paginator = MagicMock()
    paginator.paginate.return_value = [
        {"Contents": [{"Key": "p/0002.jpg"}, {"Key": "p/0001.jpg"}]},
        {"Contents": [{"Key": "p/0003.png"}]},
        {},
    ]
    client.get_paginator.return_value = paginator
    return S3Client("bucket", "us-east-1", client=client), client


def test_list_keys_paginates_and_sorts():
    s3, client = make()
    assert s3.list_keys("p/") == ["p/0001.jpg", "p/0002.jpg", "p/0003.png"]
    client.get_paginator.assert_called_with("list_objects_v2")


def test_download_creates_parent(tmp_path):
    s3, client = make()
    s3.download("p/0001.jpg", tmp_path / "images" / "0001.jpg")
    client.download_file.assert_called_once_with("bucket", "p/0001.jpg", str(tmp_path / "images" / "0001.jpg"))
    assert (tmp_path / "images").is_dir()


def test_upload_sets_content_type(tmp_path):
    s3, client = make()
    f = tmp_path / "mesh.glb"; f.write_bytes(b"glTF")
    s3.upload_file(f, "out/mesh.glb", "model/gltf-binary")
    client.upload_file.assert_called_once_with(str(f), "bucket", "out/mesh.glb", ExtraArgs={"ContentType": "model/gltf-binary"})
