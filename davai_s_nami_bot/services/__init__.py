"""Transport-agnostic service layer.

What a request does, independent of how it arrived: REST (``api/``) today, gRPC
(``proto/dsn/v1``) next. A service function takes plain arguments and an
optional ``city``, runs as that city, and returns plain dicts or raises
``errors.ServiceError``. Transport concerns stay outside: auth, request
logging, HTTP status codes / gRPC status, response envelopes.

Most functions are synchronous (SQLAlchemy, Redis): call them from async code
via ``run_in_threadpool``. Waiting for Celery tasks is async (``tasks``).
"""
