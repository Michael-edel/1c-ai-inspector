import json
import logging

from app.core.logging import JsonFormatter


def test_json_logging_keeps_only_safe_request_fields() -> None:
    record = logging.LogRecord("app.http", logging.INFO, "", 0, "http_request", (), None)
    record.fields = {"requestId": "req-1", "method": "GET", "path": "/health", "status": 200}

    payload = json.loads(JsonFormatter().format(record))

    assert payload["fields"] == record.fields
    assert "Authorization" not in json.dumps(payload)
