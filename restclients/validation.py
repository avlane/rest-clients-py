"""Decode JSON into dataclasses, checking types and reporting every problem.

``parse(Order, payload)`` walks the dataclass' type hints. Unlike a bare
``Order(**payload)`` or a hand-written ``from_dict`` it

* checks each value's type (``"5"`` is not an ``int``, ``True`` is not an ``int``),
* handles ``Optional``, ``List``, ``Dict`` and nested dataclasses,
* collects *all* problems with a JSON-path-like location, and
* ignores unknown keys (APIs add fields), unless ``strict=True``.
"""
import dataclasses
import types
import typing
from typing import Any

from restclients.errors import ApiError

_NoneType = type(None)


class ValidationError(ApiError):
    """The payload does not match the expected model."""

    def __init__(self, problems, model=None):
        self.problems = list(problems)      # [(path, message), ...]
        self.model = model
        summary = "; ".join("%s: %s" % p for p in self.problems[:5])
        if len(self.problems) > 5:
            summary += "; ... and %d more" % (len(self.problems) - 5)
        super().__init__("invalid %s payload (%s)" % (getattr(model, "__name__", "data"), summary))


def parse(model, data, strict=False):
    """Build ``model`` (a dataclass type) from decoded JSON ``data``."""
    problems = []
    result = _decode(model, data, "$", problems, strict)
    if problems:
        raise ValidationError(problems, model)
    return result


def parse_list(model, data, strict=False):
    """Parse a JSON array of ``model`` objects."""
    problems = []
    result = _decode(typing.List[model], data, "$", problems, strict)
    if problems:
        raise ValidationError(problems, model)
    return result


def _type_name(value):
    return "null" if value is None else type(value).__name__


def _decode(tp, value, path, problems, strict):
    if tp is Any:
        return value
    origin = getattr(tp, "__origin__", None)
    args = getattr(tp, "__args__", ())

    if origin is typing.Union or isinstance(tp, getattr(types, "UnionType", ())):
        args = args or tp.__args__
        if value is None and _NoneType in args:
            return None
        options = [a for a in args if a is not _NoneType]
        if len(options) == 1:
            return _decode(options[0], value, path, problems, strict)
        for option in options:
            attempt = []
            result = _decode(option, value, path, attempt, strict)
            if not attempt:
                return result
        problems.append((path, "%s matches none of the allowed types" % _type_name(value)))
        return None

    if origin is list:
        if not isinstance(value, list):
            problems.append((path, "expected an array, got %s" % _type_name(value)))
            return None
        inner = args[0] if args else Any
        return [_decode(inner, v, "%s[%d]" % (path, i), problems, strict) for i, v in enumerate(value)]

    if origin is dict:
        if not isinstance(value, dict):
            problems.append((path, "expected an object, got %s" % _type_name(value)))
            return None
        inner = args[1] if len(args) == 2 else Any
        return {k: _decode(inner, v, "%s.%s" % (path, k), problems, strict) for k, v in value.items()}

    if tp is bool:
        return _scalar(value, bool, "a boolean", path, problems)
    if tp is int:
        if isinstance(value, bool):
            problems.append((path, "expected an integer, got boolean"))
            return None
        return _scalar(value, int, "an integer", path, problems)
    if tp is float:
        if isinstance(value, int) and not isinstance(value, bool):
            return float(value)
        return _scalar(value, float, "a number", path, problems)
    if tp is str:
        return _scalar(value, str, "a string", path, problems)

    if dataclasses.is_dataclass(tp):
        return _decode_dataclass(tp, value, path, problems, strict)

    raise TypeError("unsupported type in model: %r" % (tp,))


def _scalar(value, expected, label, path, problems):
    if isinstance(value, expected):
        return value
    problems.append((path, "expected %s, got %s" % (label, _type_name(value))))
    return None


def _decode_dataclass(cls, value, path, problems, strict):
    if not isinstance(value, dict):
        problems.append((path, "expected an object, got %s" % _type_name(value)))
        return None
    hints = typing.get_type_hints(cls)
    before = len(problems)
    kwargs = {}
    for f in dataclasses.fields(cls):
        if not f.init:
            continue
        here = "%s.%s" % (path, f.name)
        if f.name not in value:
            if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING:
                problems.append((here, "required field is missing"))
            continue
        kwargs[f.name] = _decode(hints[f.name], value[f.name], here, problems, strict)
    if strict:
        known = {f.name for f in dataclasses.fields(cls)}
        for key in value:
            if key not in known:
                problems.append(("%s.%s" % (path, key), "unexpected field"))
    if len(problems) > before:
        return None
    return cls(**kwargs)
