import mimetypes
from pathlib import Path

from fastapi import APIRouter, Request, Response

from app.config import get_settings

router = APIRouter()

mimetypes.add_type("model/gltf-binary", ".glb")


@router.put("/dev-upload/{path:path}", status_code=200)
async def dev_upload_sink(path: str, request: Request) -> Response:
    """Accepts a PUT body and writes it to LOCAL_STORAGE_PATH so dev_worker.py can read it.
    Acts as an S3 replacement for mock mode; the browser's presigned-URL upload succeeds
    and the file is available on disk for downstream processing."""
    body = await request.body()
    settings = get_settings()
    dest = Path(settings.local_storage_path) / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    return Response(status_code=200)


@router.get("/dev-upload/{path:path}", status_code=200)
async def dev_download_sink(path: str) -> Response:
    """Serves a file previously written under LOCAL_STORAGE_PATH (mock mesh/preview/images);
    returns an empty 200 when it does not exist, which is what transcribe's mock relies on."""
    root = Path(get_settings().local_storage_path).resolve()
    target = (root / path).resolve()
    if target.is_file() and root in target.parents:
        media_type, _ = mimetypes.guess_type(target.name)
        return Response(content=target.read_bytes(), media_type=media_type or "application/octet-stream")
    return Response(status_code=200)
