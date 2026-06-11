from pathlib import Path

from fastapi import APIRouter, Request, Response

from app.config import get_settings

router = APIRouter()


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
    """Returns an empty 200 for any mock presigned download URL."""
    return Response(status_code=200)
