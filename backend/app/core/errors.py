"""Domain exceptions. app.api.problems maps them to RFC 9457 problem responses."""

from __future__ import annotations


class DomainError(Exception):
    status_code = 400
    title = "Bad request"

    def __init__(self, detail: str = "", **extra: object) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        self.extra = extra


class ValidationError(DomainError):
    status_code = 422
    title = "Validation failed"


class NotFoundError(DomainError):
    status_code = 404
    title = "Not found"


class ForbiddenError(DomainError):
    status_code = 403
    title = "Forbidden"


class UnauthenticatedError(DomainError):
    status_code = 401
    title = "Authentication required"


class ConflictError(DomainError):
    status_code = 409
    title = "Conflict"


class ImmutableError(ConflictError):
    title = "Record is immutable"


class DependencyUnavailableError(DomainError):
    status_code = 503
    title = "Dependency unavailable"
