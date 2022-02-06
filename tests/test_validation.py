import unittest
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from restclients.errors import ApiError
from restclients.models import Item, Order
from restclients.validation import ValidationError, parse, parse_list


@dataclass
class Settings:
    flags: Dict[str, bool] = field(default_factory=dict)
    ratio: float = 1.0
    extra: Any = None
    ident: Union[int, str] = 0


def problems_for(model, data, **kwargs):
    with unittest.TestCase().assertRaises(ValidationError) as ctx:
        parse(model, data, **kwargs)
    return ctx.exception.problems


class ParseTests(unittest.TestCase):
    def test_valid_nested_payload(self):
        order = parse(Order, {"id": 1, "customer": "Rowan Hale", "note": None,
                              "items": [{"id": 2, "name": "bolt", "price": 3}]})
        self.assertEqual(order.items[0], Item(2, "bolt", 3))
        self.assertIsNone(order.note)

    def test_unknown_keys_are_ignored_by_default(self):
        self.assertEqual(parse(Item, {"id": 1, "name": "x", "colour": "red"}), Item(1, "x", 0))

    def test_strict_rejects_unknown_keys(self):
        self.assertEqual(problems_for(Item, {"id": 1, "name": "x", "colour": "red"}, strict=True),
                         [("$.colour", "unexpected field")])

    def test_wrong_types_are_all_reported_with_paths(self):
        problems = problems_for(Order, {"id": "7", "customer": 5,
                                        "items": [{"id": 1, "name": "ok"}, {"id": True, "name": None}]})
        self.assertEqual(problems, [
            ("$.id", "expected an integer, got str"),
            ("$.customer", "expected a string, got int"),
            ("$.items[1].id", "expected an integer, got boolean"),
            ("$.items[1].name", "expected a string, got null"),
        ])

    def test_container_type_errors(self):
        self.assertEqual(problems_for(Order, {"id": 1, "customer": "c", "items": {"a": 1}}),
                         [("$.items", "expected an array, got dict")])
        self.assertEqual(problems_for(Item, ["not", "an", "object"]),
                         [("$", "expected an object, got list")])

    def test_optional_accepts_null_and_value_but_not_wrong_type(self):
        self.assertEqual(parse(Order, {"id": 1, "customer": "c", "note": "hi"}).note, "hi")
        self.assertEqual(problems_for(Order, {"id": 1, "customer": "c", "note": 5}),
                         [("$.note", "expected a string, got int")])

    def test_floats_accept_ints_dicts_check_values_any_passes(self):
        s = parse(Settings, {"flags": {"a": True}, "ratio": 2, "extra": [1, "x"], "ident": "abc"})
        self.assertEqual((s.ratio, s.flags, s.extra, s.ident), (2.0, {"a": True}, [1, "x"], "abc"))
        self.assertIsInstance(s.ratio, float)
        self.assertEqual(problems_for(Settings, {"flags": {"a": 1}}),
                         [("$.flags.a", "expected a boolean, got int")])

    def test_union_that_matches_nothing(self):
        self.assertEqual(problems_for(Settings, {"ident": 1.5}),
                         [("$.ident", "float matches none of the allowed types")])

    def test_parse_list(self):
        items = parse_list(Item, [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}])
        self.assertEqual([i.id for i in items], [1, 2])
        with self.assertRaises(ValidationError):
            parse_list(Item, [{"id": 1}])

    def test_error_message_is_readable_and_catchable_as_api_error(self):
        with self.assertRaises(ApiError) as ctx:
            parse(Item, {"id": "x"})
        self.assertIn("invalid Item payload", str(ctx.exception))
        self.assertIn("$.id", str(ctx.exception))

    def test_long_problem_lists_are_summarised(self):
        with self.assertRaises(ValidationError) as ctx:
            parse_list(Item, [{} for _ in range(5)])
        self.assertEqual(len(ctx.exception.problems), 10)
        self.assertIn("and 5 more", ctx.exception.message)

    def test_unsupported_annotation_is_a_programming_error(self):
        @dataclass
        class Bad:
            when: complex

        with self.assertRaises(TypeError):
            parse(Bad, {"when": 1})


if __name__ == "__main__":
    unittest.main()
