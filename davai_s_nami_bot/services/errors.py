"""Errors a service raises; each transport maps them to its own status codes."""


class ServiceError(Exception):
    """Base class. REST: 400, gRPC: INVALID_ARGUMENT unless a subclass says otherwise."""


class NotFound(ServiceError):
    """REST 404, gRPC NOT_FOUND."""


class InvalidArgument(ServiceError):
    """REST 400, gRPC INVALID_ARGUMENT."""
