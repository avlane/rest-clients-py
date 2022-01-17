"""Typed models for API payloads, as dataclasses.

Dicts are fine for a script. Once a client is shared, a dataclass tells the
reader (and the editor) what the API returns. ``from_dict`` is written by hand
here on purpose: it is the part that later gets replaced by generic validation.
"""
from dataclasses import asdict, dataclass, field
from typing import List, Optional


@dataclass
class Item:
    id: int
    name: str
    price: int = 0

    @classmethod
    def from_dict(cls, data):
        return cls(id=data["id"], name=data["name"], price=data.get("price", 0))

    def to_dict(self):
        return asdict(self)


@dataclass
class Order:
    id: int
    customer: str
    items: List[Item] = field(default_factory=list)
    note: Optional[str] = None

    @classmethod
    def from_dict(cls, data):
        return cls(
            id=data["id"],
            customer=data["customer"],
            items=[Item.from_dict(i) for i in data.get("items", [])],
            note=data.get("note"),
        )

    def to_dict(self):
        return asdict(self)

    @property
    def total(self):
        return sum(item.price for item in self.items)
