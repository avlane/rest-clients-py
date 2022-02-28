"""A client for the test server's /items API, built on restclients.base.ApiClient."""
from __future__ import annotations

from collections.abc import Iterator

from restclients.base import ApiClient
from restclients.errors import NotFound
from restclients.models import Item, Order
from restclients.validation import parse


class ItemsClient(ApiClient):
    def get_item(self, item_id: int) -> Item:
        return self._get_model("/items/%d" % item_id, Item)

    def find_item(self, item_id: int) -> Item | None:
        """Like get_item but returns None instead of raising NotFound."""
        try:
            return self.get_item(item_id)
        except NotFound:
            return None

    def list_items(self) -> Iterator[Item]:
        return self._list_models("/items", Item)

    def create_item(self, name: str, price: int = 0) -> Item:
        return self._post_model("/items", Item, {"name": name, "price": price})

    def rename_item(self, item_id: int, name: str) -> Item:
        return parse(Item, self._patch("/items/%d" % item_id, {"name": name}))

    def delete_item(self, item_id: int) -> None:
        self._delete("/items/%d" % item_id)

    def get_order(self, order_id: int) -> Order:
        return self._get_model("/orders/%d" % order_id, Order)
