from fastapi import HTTPException, status


class AppError(Exception):
    def __init__(self, code: str, message: str, http_status: int):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


class NotFoundError(AppError):
    def __init__(self, message: str):
        super().__init__("NOT_FOUND", message, status.HTTP_404_NOT_FOUND)


class ConflictError(AppError):
    def __init__(self, message: str):
        super().__init__("CONFLICT", message, status.HTTP_409_CONFLICT)


class ForbiddenError(AppError):
    def __init__(self, message: str):
        super().__init__("FORBIDDEN", message, status.HTTP_403_FORBIDDEN)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Authentication required"):
        super().__init__("UNAUTHORIZED", message, status.HTTP_401_UNAUTHORIZED)


class ValidationAppError(AppError):
    def __init__(self, message: str):
        super().__init__("VALIDATION_ERROR", message, status.HTTP_400_BAD_REQUEST)


def raise_http(error: AppError) -> None:
    raise HTTPException(
        status_code=error.http_status,
        detail={"error": {"code": error.code, "message": error.message}},
    )
