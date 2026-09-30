from datetime import date, datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, create_model
from sqlalchemy import JSON, LargeBinary, func, select
from sqlalchemy.orm import Session

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int


class ErrorDetail(BaseModel):
    code: str
    message: str
    fields: list[dict[str, str]] = []
    details: Any = None
    request_id: str = ""


class ErrorBody(BaseModel):
    error: ErrorDetail


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": ErrorBody, "description": description}
    for status, description in {
        401: "Missing, expired, or revoked session",
        403: "Authenticated but not permitted",
        404: "Not found in the active institution",
        409: "Business-rule conflict",
        422: "Request validation failed",
        429: "Rate limit or lockout",
    }.items()
}


def out_schema(model, name: str | None = None, exclude: tuple[str, ...] = (), **extra) -> type[BaseModel]:
    fields: dict[str, Any] = {}
    for column in model.__table__.columns:
        if column.key in exclude or isinstance(column.type, LargeBinary):
            continue
        if isinstance(column.type, JSON):
            python_type: Any = Any
        else:
            try:
                python_type = column.type.python_type
            except NotImplementedError:
                python_type = Any
        fields[column.key] = (python_type | None, None) if column.nullable else (python_type, ...)
    fields.update(extra)
    return create_model(name or f"{model.__name__}Out", __config__=ConfigDict(from_attributes=True), **fields)


def as_dict(record, **extra) -> dict[str, Any]:
    data = {column.key: getattr(record, column.key) for column in record.__table__.columns
            if not isinstance(column.type, LargeBinary)}
    data.update(extra)
    return data


def paginate(session: Session, statement, page: int, size: int, serialize=as_dict) -> dict[str, Any]:
    page, size = max(page, 1), min(max(size, 1), 200)
    total = session.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    rows = session.scalars(statement.limit(size).offset((page - 1) * size)).all()
    return {"items": [serialize(row) for row in rows], "total": total, "page": page, "size": size}


def paginate_rows(session: Session, statement, page: int, size: int, serialize) -> dict[str, Any]:
    page, size = max(page, 1), min(max(size, 1), 200)
    total = session.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    rows = session.execute(statement.limit(size).offset((page - 1) * size)).all()
    return {"items": [serialize(*row) for row in rows], "total": total, "page": page, "size": size}


def iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value else None
