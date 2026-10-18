import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.auth.schemas import RegisterRequest
from backend.errors import AppError, install_error_handlers
from backend.logging import JSONFormatter, get_logger, request_id_context
from backend.middleware import RequestLoggingMiddleware


@pytest.fixture
def observed_app():
    app = FastAPI()
    install_error_handlers(app)
    app.add_middleware(RequestLoggingMiddleware)

    @app.get("/ok")
    def ok():
        get_logger(__name__).info("Example event", extra={"event": "example"})
        return {"ok": True}

    @app.get("/expected")
    def expected():
        raise AppError("EXAMPLE_CONFLICT", "Operation conflicts.", 409)

    @app.get("/failure")
    def failure():
        raise RuntimeError("password=TOP_SECRET database credentials")

    @app.get("/unauthorized")
    def unauthorized():
        raise HTTPException(401, "TOP_SECRET", headers={"WWW-Authenticate": "Bearer"})

    @app.post("/validate")
    def validate(payload: RegisterRequest):
        return {"ok": True}

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JSONFormatter())
    logger = logging.getLogger("backend")
    logger.addHandler(handler)
    try:
        with TestClient(app) as client:
            yield client, stream
    finally:
        logger.removeHandler(handler)


@pytest.mark.parametrize(
    "path,status,code",
    [
        ("/expected", 409, "EXAMPLE_CONFLICT"),
        ("/failure", 500, "INTERNAL_ERROR"),
        ("/missing", 404, "HTTP_404"),
        ("/unauthorized", 401, "HTTP_401"),
    ],
)
def test_errors_have_safe_envelope_and_correlated_logs(
    observed_app, path, status, code
):
    client, stream = observed_app
    response = client.get(path + "?token=TOP_SECRET", headers={"Cookie": "TOP_SECRET"})
    assert response.status_code == status
    error = response.json()["error"]
    assert error["code"] == code
    assert error["request_id"] == response.headers["x-request-id"]
    UUID(error["request_id"])
    assert "TOP_SECRET" not in response.text + stream.getvalue()
    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert all(record["request_id"] == error["request_id"] for record in records)
    if status == 500:
        failure = next(record for record in records if "exception" in record)
        assert failure["exception"]["type"] == "RuntimeError"
        assert failure["exception"]["frames"]
    if status == 401:
        assert response.headers["www-authenticate"] == "Bearer"


def test_validation_never_echoes_secret_inputs_or_extra_field_names(observed_app):
    client, stream = observed_app
    response = client.post(
        "/validate",
        json={"username": "alice", "password": "TOP_SECRET", "TOP_SECRET": "value"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "TOP_SECRET" not in response.text + stream.getvalue()
    assert "password" in response.text


def test_request_ids_are_isolated_and_client_id_is_not_trusted(observed_app):
    client, stream = observed_app

    def request(_):
        return client.get("/ok", headers={"X-Request-ID": "client-controlled"})

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(request, range(8)))
    ids = {response.headers["x-request-id"] for response in responses}
    assert len(ids) == 8
    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert {record["request_id"] for record in records} == ids
    assert "client-controlled" not in stream.getvalue()
    assert request_id_context.get() is None


def test_formatter_ignores_unapproved_extra_and_encodes_newlines():
    record = logging.LogRecord(
        "backend.test", logging.INFO, __file__, 1, "safe message\nsecond line", (), None
    )
    record.password = "TOP_SECRET"
    result = JSONFormatter().format(record)
    assert len(result.splitlines()) == 1
    assert "TOP_SECRET" not in result
    assert json.loads(result)["request_id"] is None
