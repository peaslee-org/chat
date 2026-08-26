"""The dev-upload sink GET serves a stored file (needed for the mock mesh/preview)."""
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.transcribe import dev


def make_app():
    app = FastAPI()
    app.include_router(dev.router, prefix="/api/v1/transcribe")
    return app


async def test_get_returns_file_bytes_with_content_type(tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "mesh.glb").write_bytes(b"glTF")
    with patch.object(dev, "get_settings", return_value=MagicMock(local_storage_path=str(tmp_path))):
        async with AsyncClient(transport=ASGITransport(app=make_app()), base_url="http://t") as ac:
            r = await ac.get("/api/v1/transcribe/dev-upload/x/mesh.glb")
    assert r.status_code == 200
    assert r.content == b"glTF"
    assert r.headers["content-type"].startswith("model/gltf-binary")


async def test_get_missing_file_is_empty_200(tmp_path):
    with patch.object(dev, "get_settings", return_value=MagicMock(local_storage_path=str(tmp_path))):
        async with AsyncClient(transport=ASGITransport(app=make_app()), base_url="http://t") as ac:
            r = await ac.get("/api/v1/transcribe/dev-upload/nope.bin")
    assert r.status_code == 200
    assert r.content == b""


async def test_put_then_get_roundtrip(tmp_path):
    with patch.object(dev, "get_settings", return_value=MagicMock(local_storage_path=str(tmp_path))):
        async with AsyncClient(transport=ASGITransport(app=make_app()), base_url="http://t") as ac:
            await ac.put("/api/v1/transcribe/dev-upload/p/0001.jpg", content=b"\xff\xd8")
            r = await ac.get("/api/v1/transcribe/dev-upload/p/0001.jpg")
    assert r.content == b"\xff\xd8"
    assert r.headers["content-type"] == "image/jpeg"
