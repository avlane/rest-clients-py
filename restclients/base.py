"""ApiClient: a base class for writing a client for one specific API.

It wraps any ``HttpClient`` (urllib, requests, ...) and adds the things every
API wrapper ends up needing: JSON helpers, a pagination strategy, and context
manager support. Subclasses add one small method per endpoint with proper type
hints, and never touch the transport.
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Dict

from restclients import pagination
from restclients.client import HttpClient
from restclients.validation import parse, parse_list

JsonObject = Dict[str, Any]  # a runtime alias, so it stays typing.Dict until 3.9 is the floor


class ApiClient:
    #: one of "pages", "links", "cursor" or None (endpoint returns everything)
    pagination = None
    page_size = 50

    def __init__(self, http: HttpClient) -> None:
        self.http = http

    def __enter__(self) -> "ApiClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        close = getattr(self.http, "close", None)
        if close is not None:
            close()

    # -- building blocks for subclasses -----------------------------------
    def _call(self, method: str, path: str, params: dict[str, Any] | None = None,
              headers: dict[str, Any] | None = None, body: Any = None) -> Any:
        """One request for generated clients: drops None-valued params/headers, returns JSON.

        An empty body (204) gives None.
        """
        params = {k: v for k, v in (params or {}).items() if v is not None}
        headers = {k: str(v) for k, v in (headers or {}).items() if v is not None}
        return self.http.request(method, path, params=params, headers=headers, json=body).json()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self.http.get_json(path, params=params)

    def _post(self, path: str, payload: Any = None) -> Any:
        return self.http.post(path, json=payload).json()

    def _put(self, path: str, payload: Any = None) -> Any:
        return self.http.put(path, json=payload).json()

    def _patch(self, path: str, payload: Any = None) -> Any:
        return self.http.patch(path, json=payload).json()

    def _delete(self, path: str) -> None:
        self.http.delete(path)

    def _get_model(self, path: str, model: type, params: dict[str, Any] | None = None) -> Any:
        """GET and decode into a dataclass; a bad payload raises ValidationError."""
        return parse(model, self._get(path, params))

    def _list_models(self, path: str, model: type, params: dict[str, Any] | None = None,
                     **options: Any) -> Iterator[Any]:
        """Iterate a collection lazily, decoding each element into ``model``."""
        for raw in self._iterate(path, params, **options):
            yield parse(model, raw)

    def _post_model(self, path: str, model: type, payload: Any = None) -> Any:
        return parse(model, self._post(path, payload))

    def _iterate(self, path: str, params: dict[str, Any] | None = None,
                 **options: Any) -> Iterator[Any]:
        """Iterate over a collection using the class's pagination strategy."""
        if self.pagination == "pages":
            return pagination.paginate_pages(self.http, path, params, limit=self.page_size, **options)
        if self.pagination == "links":
            return pagination.paginate_links(self.http, path, params, **options)
        if self.pagination == "cursor":
            return pagination.paginate_cursor(self.http, path, params, **options)
        return iter(self._get(path, params))
