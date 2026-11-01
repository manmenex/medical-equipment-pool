from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, BeforeValidator

T = TypeVar("T")

# Accepts uuid.UUID (or any object) coming straight off an ORM model and
# coerces it to str, so response schemas don't reject SQLAlchemy UUID columns.
UUIDStr = Annotated[str, BeforeValidator(lambda v: str(v) if v is not None else v)]


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None
    total: int


class ErrorResponse(BaseModel):
    detail: str
    code: str
    status: int
