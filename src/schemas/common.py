from typing import Generic, TypeVar, Any
from pydantic import BaseModel

T = TypeVar("T")


class PaginationMeta(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int


class ActionMeta(BaseModel):
    action: str


class DataResponse(BaseModel, Generic[T]):
    data: T


class PaginatedResponse(BaseModel, Generic[T]):
    data: list[T]
    meta: PaginationMeta


class ActionResponse(BaseModel, Generic[T]):
    data: T
    meta: ActionMeta


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
