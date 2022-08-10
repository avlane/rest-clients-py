"""Structured (JSON lines) logging for HTTP traffic, with secrets removed."""
import contextvars
import json
import logging
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SENSITIVE_HEADERS = frozenset(["authorization", "proxy-authorization", "cookie", "set-cookie",
                               "x-api-key"])
SENSITIVE_PARAMS = frozenset(["token", "access_token", "refresh_token", "api_key", "apikey", "key",
                              "secret", "client_secret", "password", "signature", "code"])
REDACTED = "***"

#: Set this around a unit of work (a job, an incoming request) and every HTTP call
#: made inside it reuses the id, so the logs of different services can be joined.
correlation_id = contextvars.ContextVar("restclients_correlation_id", default=None)

_STANDARD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


def redact_headers(headers, names=SENSITIVE_HEADERS):
    """Copy of ``headers`` (a mapping) with credentials replaced by ``***``."""
    return {k: (REDACTED if k.lower() in names else v) for k, v in dict(headers).items()}


def redact_url(url, params=SENSITIVE_PARAMS):
    """``url`` with secret-looking query parameter values and any password replaced."""
    parts = urlsplit(url)
    netloc = parts.netloc
    if "@" in netloc:
        userinfo, _, host = netloc.rpartition("@")
        user = userinfo.split(":", 1)[0]
        netloc = "%s:%s@%s" % (user, REDACTED, host) if ":" in userinfo else netloc
    query = parse_qsl(parts.query, keep_blank_values=True)
    if any(k.lower() in params for k, _ in query):
        query = [(k, REDACTED if k.lower() in params else v) for k, v in query]
        return urlunsplit(parts._replace(netloc=netloc, query=urlencode(query, safe="*")))
    return urlunsplit(parts._replace(netloc=netloc))


class JsonFormatter(logging.Formatter):
    """One JSON object per line: timestamp, level, logger, message and any ``extra`` fields."""

    def format(self, record):
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, sort_keys=False)
