"""Typed models for API payloads, as dataclasses.

Dicts are fine for a script. Once a client is shared, a dataclass tells the
reader (and the editor) what the API returns. Decoding and type checking is
done by :mod:`restclients.validation`, driven by the annotations below.
"""
from dataclasses import asdict, dataclass, field
from typing import Optional

from restclients.validation import parse


class Model:
    """Mixin giving dataclasses ``from_dict`` / ``to_dict``."""

    @classmethod
    def from_dict(cls, data, strict=False):
        return parse(cls, data, strict)

    def to_dict(self):
        return asdict(self)


@dataclass
class Item(Model):
    id: int
    name: str
    price: int = 0


@dataclass
class Order(Model):
    id: int
    customer: str
    items: list[Item] = field(default_factory=list)
    note: Optional[str] = None

    @property
    def total(self):
        return sum(item.price for item in self.items)
