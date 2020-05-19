"""ApiClient: a base class for writing a client for one specific API.

It wraps any ``HttpClient`` (urllib, requests, ...) and adds the things every
API wrapper ends up needing: JSON helpers, a pagination strategy, and context
manager support. Subclasses add one small method per endpoint with proper type
hints, and never touch the transport.
"""
from typing import Any, Dict, Iterator, Optional

from restclients import pagination
from restclients.client import HttpClient

JsonObject = Dict[str, Any]


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
    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self.http.get_json(path, params=params)

    def _post(self, path: str, payload: Any = None) -> Any:
        return self.http.post(path, json=payload).json()

    def _put(self, path: str, payload: Any = None) -> Any:
        return self.http.put(path, json=payload).json()

    def _patch(self, path: str, payload: Any = None) -> Any:
        return self.http.patch(path, json=payload).json()

    def _delete(self, path: str) -> None:
        self.http.delete(path)

    def _iterate(self, path: str, params: Optional[Dict[str, Any]] = None,
                 **options: Any) -> Iterator[Any]:
        """Iterate over a collection using the class's pagination strategy."""
        if self.pagination == "pages":
            return pagination.paginate_pages(self.http, path, params, limit=self.page_size, **options)
        if self.pagination == "links":
            return pagination.paginate_links(self.http, path, params, **options)
        if self.pagination == "cursor":
            return pagination.paginate_cursor(self.http, path, params, **options)
        return iter(self._get(path, params))
