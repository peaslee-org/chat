from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse


class NotFoundError(Exception):
    pass


class ForbiddenError(Exception):
    pass


class AppException(Exception):
    status_code: int = 500
    detail: str = "An error occurred"

    def __init__(self, detail: str | None = None):
        self.detail = detail if detail is not None else self.__class__.detail
        super().__init__(self.detail)


class ConflictError(AppException):
    status_code = 409
    detail = "Conflict"


class ConcurrentJobLimitExceeded(AppException):
    status_code = 429
    detail = "Maximum concurrent jobs reached"


class AudioUploadMissing(AppException):
    status_code = 422
    detail = "Audio file not found at expected S3 location"


class AudioValidationError(AppException):
    """Raised with an error_code: duration_too_short | duration_too_long | unsupported_format"""
    status_code = 422

    def __init__(self, error_code: str):
        self.error_code = error_code
        super().__init__(detail=error_code)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError):
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})

    @app.exception_handler(ForbiddenError)
    async def forbidden_handler(request: Request, exc: ForbiddenError):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": str(exc)})

    @app.exception_handler(AudioValidationError)
    async def audio_validation_handler(request: Request, exc: AudioValidationError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "error_code": exc.error_code},
        )

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )
