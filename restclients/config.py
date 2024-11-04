"""Build a client from a TOML file.

    [client]
    base_url = "https://api.example.test"
    timeout = [3.05, 10]            # seconds, or a (connect, read) pair
    transport = "urllib"            # urllib | keepalive | requests | httpx
    [client.headers]
    X-Team = "docs"

    [retry]
    max_attempts = 4
    backoff_base = 0.5

    [rate_limit]
    per_second = 5
    burst = 10

    [auth]
    type = "bearer"                 # basic | bearer | api_key
    token_env = "EXAMPLE_API_TOKEN" # secrets come from the environment, never the file

Unknown keys are errors, so a typo does not silently disable retries.
"""
import os
from dataclasses import dataclass, field
from typing import Optional, Union

from restclients.auth import ApiKeyAuth, BasicAuth, BearerAuth
from restclients.errors import ApiError
from restclients.ratelimit import TokenBucket
from restclients.retry import RetryPolicy
from restclients.validation import ValidationError, parse

try:
    import tomllib                      # Python 3.11+
except ModuleNotFoundError:             # older interpreters can install the same parser as "tomli"
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        tomllib = None

TRANSPORTS = ("urllib", "keepalive", "requests", "httpx")


class ConfigError(ApiError):
    """The configuration file is missing, unreadable or invalid."""


@dataclass
class ClientSection:
    base_url: str
    timeout: Union[float, list[float]] = 10.0
    transport: str = "urllib"
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class RetrySection:
    max_attempts: int = 3
    backoff_base: float = 0.5
    max_delay: float = 30.0
    max_retry_after: float = 60.0


@dataclass
class RateLimitSection:
    per_second: float
    burst: int = 1


@dataclass
class AuthSection:
    type: str
    username: Optional[str] = None
    password_env: Optional[str] = None
    token_env: Optional[str] = None
    header: str = "X-API-Key"


@dataclass
class Config:
    client: ClientSection
    retry: Optional[RetrySection] = None
    rate_limit: Optional[RateLimitSection] = None
    auth: Optional[AuthSection] = None


def load_config(path):
    """Read and validate a TOML file into a :class:`Config`."""
    if tomllib is None:
        raise ConfigError("reading TOML needs Python 3.11+ (or: pip install tomli)")
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except OSError as exc:
        raise ConfigError("cannot read %s: %s" % (path, exc.strerror or exc)) from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError("%s is not valid TOML: %s" % (path, exc)) from None
    return parse_config(data)


def parse_config(data):
    try:
        config = parse(Config, data, strict=True)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from None
    if config.client.transport not in TRANSPORTS:
        raise ConfigError("client.transport must be one of %s, not %r"
                          % (", ".join(TRANSPORTS), config.client.transport))
    if isinstance(config.client.timeout, list) and len(config.client.timeout) != 2:
        raise ConfigError("client.timeout must be a number or a [connect, read] pair")
    return config


def build_auth(section, environ=None):
    environ = os.environ if environ is None else environ
    if section is None:
        return None

    def secret(name, what):
        if not name:
            raise ConfigError("auth.%s is required for type %r" % (what, section.type))
        if name not in environ:
            raise ConfigError("environment variable %s (auth.%s) is not set" % (name, what))
        return environ[name]

    if section.type == "bearer":
        return BearerAuth(secret(section.token_env, "token_env"))
    if section.type == "api_key":
        return ApiKeyAuth(secret(section.token_env, "token_env"), section.header)
    if section.type == "basic":
        if not section.username:
            raise ConfigError("auth.username is required for type 'basic'")
        return BasicAuth(section.username, secret(section.password_env, "password_env"))
    raise ConfigError("auth.type must be basic, bearer or api_key, not %r" % section.type)


def build_client(config, environ=None, session=None):
    """Create the configured client. ``session`` is injected into requests/httpx transports."""
    settings = config.client
    timeout = tuple(settings.timeout) if isinstance(settings.timeout, list) else settings.timeout
    kwargs = {"base_url": settings.base_url, "headers": settings.headers, "timeout": timeout,
              "auth": build_auth(config.auth, environ)}
    if config.retry:
        kwargs["retry"] = RetryPolicy(config.retry.max_attempts, config.retry.backoff_base,
                                      config.retry.max_delay,
                                      max_retry_after=config.retry.max_retry_after)
    if config.rate_limit:
        kwargs["rate_limiter"] = TokenBucket(config.rate_limit.per_second, config.rate_limit.burst)

    if settings.transport == "urllib":
        from restclients.urllib_client import UrllibClient
        return UrllibClient(**kwargs)
    if settings.transport == "keepalive":
        from restclients.keepalive_client import KeepAliveClient
        return KeepAliveClient(**kwargs)
    if settings.transport == "requests":
        from restclients.requests_client import RequestsClient
        return RequestsClient(session, **kwargs)
    from restclients.httpx_client import HttpxClient
    return HttpxClient(session, **kwargs)
