from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.gpu.deps import get_gpu_controller_by_family, is_admin
from app.dependencies import get_current_user
from app.schemas.gpu import GpuStateResponse, GpuUsageResponse
from app.services.gpu_controller import GpuCapExceeded, GpuController, GpuNoWorker

router = APIRouter()


def _require(ctl: GpuController | None) -> GpuController:
    if ctl is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="GPU controller disabled")
    return ctl


@router.get("/state", response_model=GpuStateResponse)
async def gpu_state(ctl=Depends(get_gpu_controller_by_family), _user: dict = Depends(get_current_user)):
    return await _require(ctl).get_state()


@router.post("/warm", response_model=GpuStateResponse)
async def gpu_warm(ctl=Depends(get_gpu_controller_by_family), user: dict = Depends(get_current_user)):
    try:
        return await _require(ctl).ensure_worker("warm", user["sub"], is_admin=is_admin(user))
    except GpuCapExceeded as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=e.reason)


@router.post("/release", response_model=GpuStateResponse)
async def gpu_release(mode: Literal["graceful", "immediate"] = Query("graceful"),
                      ctl=Depends(get_gpu_controller_by_family), user: dict = Depends(get_current_user)):
    """Admin-only: make the family's live worker exit. graceful = after its current job;
    immediate = abort the job too (its message is redelivered to the next worker)."""
    if not is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin only")
    try:
        return await _require(ctl).release(mode, user["sub"])
    except GpuNoWorker as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.get("/usage", response_model=GpuUsageResponse)
async def gpu_usage(ctl=Depends(get_gpu_controller_by_family), user: dict = Depends(get_current_user)):
    return await _require(ctl).usage(user["sub"])
