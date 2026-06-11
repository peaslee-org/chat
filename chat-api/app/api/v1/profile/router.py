from fastapi import APIRouter

from app.api.v1.profile import profile

router = APIRouter()

router.include_router(profile.router, prefix="", tags=["profile"])
