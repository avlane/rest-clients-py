import unittest

from restclients import errors
from restclients.optimistic import ConflictRetriesExhausted, update_resource
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


class ConditionalWriteTests(unittest.TestCase):
    def setUp(self):
        self.server = ApiServer().__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        self.client = UrllibClient(base_url=self.server.url)

    def test_items_carry_an_etag_that_changes_on_write(self):
        first = self.client.get("/items/1").headers["ETag"]
        again = self.client.get("/items/1").headers["ETag"]
        self.client.patch("/items/1", json={"name": "changed"})
        self.assertEqual(first, again)
        self.assertNotEqual(first, self.client.get("/items/1").headers["ETag"])

    def test_matching_if_match_succeeds(self):
        etag = self.client.get("/items/2").headers["ETag"]
        resp = self.client.patch("/items/2", json={"price": 77}, headers={"If-Match": etag})
        self.assertEqual(resp.json()["price"], 77)

    def test_stale_if_match_is_a_412_and_changes_nothing(self):
        stale = self.client.get("/items/3").headers["ETag"]
        self.client.patch("/items/3", json={"name": "someone else was here"})
        with self.assertRaises(errors.PreconditionFailed) as ctx:
            self.client.patch("/items/3", json={"name": "my lost update"}, headers={"If-Match": stale})
        self.assertEqual(ctx.exception.status, 412)
        self.assertEqual(self.client.get_json("/items/3")["name"], "someone else was here")
        self.assertNotEqual(ctx.exception.headers["ETag"], stale)       # the current version is offered

    def test_without_if_match_the_last_writer_wins_silently(self):
        """The lost-update problem the header exists to prevent."""
        self.client.patch("/items/4", json={"name": "first"})
        self.client.patch("/items/4", json={"name": "second"})
        self.assertEqual(self.client.get_json("/items/4")["name"], "second")

    def test_428_when_the_server_requires_a_condition(self):
        with self.assertRaises(errors.PreconditionRequired):
            self.client.patch("/items/5", params={"require_if_match": 1}, json={"price": 1})

    def test_conditional_delete(self):
        stale = self.client.get("/items/6").headers["ETag"]
        self.client.patch("/items/6", json={"price": 1})
        with self.assertRaises(errors.PreconditionFailed):
            self.client.delete("/items/6", headers={"If-Match": stale})
        self.client.delete("/items/6", headers={"If-Match": self.client.get("/items/6").headers["ETag"]})
        with self.assertRaises(errors.NotFound):
            self.client.get("/items/6")


class UpdateResourceTests(unittest.TestCase):
    def setUp(self):
        self.server = ApiServer().__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        self.client = UrllibClient(base_url=self.server.url)

    def test_simple_update(self):
        update_resource(self.client, "/items/7", lambda item: dict(item, price=item["price"] + 1),
                        method="PATCH")
        self.assertEqual(self.client.get_json("/items/7")["price"], 36)

    def test_retries_on_top_of_a_concurrent_change(self):
        rival_writes = []

        def change(item):
            if not rival_writes:                      # a rival writes between our read and our write
                rival_writes.append(self.client.patch("/items/8", json={"price": 1000}))
            return dict(item, name=item["name"] + "!", price=item["price"] + 1)

        conflicts = []
        update_resource(self.client, "/items/8", change, method="PATCH",
                        on_conflict=lambda n, exc: conflicts.append(n))
        final = self.client.get_json("/items/8")
        self.assertEqual(conflicts, [1])
        self.assertEqual((final["name"], final["price"]), ("item-08!", 1001))   # rival's value kept, ours applied

    def test_gives_up_after_max_attempts(self):
        def change(item):
            self.client.patch("/items/9", json={"price": item["price"] + 1})      # always beaten
            return item

        with self.assertRaises(ConflictRetriesExhausted) as ctx:
            update_resource(self.client, "/items/9", change, method="PATCH", max_attempts=3)
        self.assertIsInstance(ctx.exception.__cause__, errors.PreconditionFailed)
        self.assertIn("3 conflicting", ctx.exception.message)

    def test_resource_without_etag_is_a_clear_error(self):
        with self.assertRaisesRegex(ValueError, "no ETag"):
            update_resource(self.client, "/pages", lambda d: d)

    def test_other_errors_propagate(self):
        with self.assertRaises(errors.NotFound):
            update_resource(self.client, "/items/999", lambda d: d)


if __name__ == "__main__":
    unittest.main()
