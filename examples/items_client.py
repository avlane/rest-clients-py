"""A client for the test server's /items API, built on restclients.base.ApiClient."""
from __future__ import annotations

from collections.abc import Iterator
from restclients.base import ApiClient, JsonObject
from restclients.errors import NotFound


class ItemsClient(ApiClient):
    def get_item(self, item_id: int) -> JsonObject:
        return self._get("/items/%d" % item_id)

    def find_item(self, item_id: int) -> JsonObject | None:
        """Like get_item but returns None instead of raising NotFound."""
        try:
            return self.get_item(item_id)
        except NotFound:
            return None

    def list_items(self) -> Iterator[JsonObject]:
        return self._iterate("/items")

    def create_item(self, name: str, price: int = 0) -> JsonObject:
        return self._post("/items", {"name": name, "price": price})

    def rename_item(self, item_id: int, name: str) -> JsonObject:
        return self._patch("/items/%d" % item_id, {"name": name})

    def delete_item(self, item_id: int) -> None:
        self._delete("/items/%d" % item_id)
