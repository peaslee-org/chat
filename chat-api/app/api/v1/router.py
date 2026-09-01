from fastapi import APIRouter

from app.api.v1.endpoints import chat, conversations, health, models
from app.api.v1.transcribe import router as transcribe_router
from app.api.v1.gpu import router as gpu_router
from app.api.v1.photogrammetry import router as photogrammetry_router
from app.api.v1.admin.router import router as admin_router
from app.api.v1.profile.profile import router as profile_router
from app.api.v1.public import router as public_router

router = APIRouter()

router.include_router(health.router, prefix="/health", tags=["health"])
router.include_router(chat.router, prefix="/chat", tags=["chat"])
router.include_router(conversations.router, prefix="/conversations", tags=["conversations"])
router.include_router(models.router, prefix="/models", tags=["models"])
router.include_router(transcribe_router, prefix="/transcribe", tags=["transcribe"])
router.include_router(gpu_router, prefix="/gpu", tags=["gpu"])
router.include_router(photogrammetry_router, prefix="/photogrammetry", tags=["photogrammetry"])
router.include_router(admin_router, prefix="/admin", tags=["admin"])
router.include_router(profile_router, prefix="/profile", tags=["profile"])
router.include_router(public_router, prefix="/public", tags=["public"])
