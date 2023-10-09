import unittest

from restclients import errors
from restclients._compat import batched
from restclients.bulk import batch_key, post_in_batches
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


class BatchedTests(unittest.TestCase):
    def test_chunks(self):
        self.assertEqual(list(batched(range(7), 3)), [(0, 1, 2), (3, 4, 5), (6,)])

    def test_exact_multiple_and_empty(self):
        self.assertEqual(list(batched("abcd", 2)), [("a", "b"), ("c", "d")])
        self.assertEqual(list(batched([], 3)), [])

    def test_accepts_one_shot_iterators(self):
        self.assertEqual(list(batched(iter(range(5)), 2)), [(0, 1), (2, 3), (4,)])

    def test_invalid_size(self):
        with self.assertRaises(ValueError):
            list(batched([1], 0))


class PostInBatchesTests(unittest.TestCase):
    def setUp(self):
        self.server = ApiServer().__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)
        self.client = UrllibClient(base_url=self.server.url)
        self.records = [{"sku": "A%03d" % n, "qty": n} for n in range(25)]

    def test_splits_into_requests_the_server_accepts(self):
        results = post_in_batches(self.client, "/bulk", self.records, batch_size=10)
        self.assertEqual([r["accepted"] for r in results], [10, 10, 5])
        self.assertEqual(len(self.server.bulk_records), 25)
        self.assertEqual(self.server.bulk_records[0], {"sku": "A000", "qty": 0})

    def test_oversized_batches_are_refused_by_the_server(self):
        with self.assertRaises(errors.ClientError) as ctx:
            post_in_batches(self.client, "/bulk", self.records, batch_size=11)
        self.assertEqual(ctx.exception.status, 413)

    def test_rerunning_a_job_does_not_duplicate_records(self):
        post_in_batches(self.client, "/bulk", self.records, batch_size=10, job_id="import-7")
        again = post_in_batches(self.client, "/bulk", self.records, batch_size=10, job_id="import-7")
        self.assertEqual(len(self.server.bulk_records), 25)       # replayed, not re-inserted
        self.assertEqual([r["accepted"] for r in again], [10, 10, 5])

    def test_a_new_job_id_is_new_work(self):
        post_in_batches(self.client, "/bulk", self.records[:10], batch_size=10, job_id="a")
        post_in_batches(self.client, "/bulk", self.records[:10], batch_size=10, job_id="b")
        self.assertEqual(len(self.server.bulk_records), 20)

    def test_batch_key_depends_on_job_position_and_contents(self):
        batch = ({"a": 1},)
        base = batch_key("j", 0, batch)
        self.assertEqual(base, batch_key("j", 0, batch))
        self.assertNotEqual(base, batch_key("k", 0, batch))
        self.assertNotEqual(base, batch_key("j", 1, batch))
        self.assertNotEqual(base, batch_key("j", 0, ({"a": 2},)))
        self.assertEqual(batch_key("j", 0, ({"a": 1, "b": 2},)), batch_key("j", 0, ({"b": 2, "a": 1},)))

    def test_empty_input_sends_nothing(self):
        self.assertEqual(post_in_batches(self.client, "/bulk", []), [])
        self.assertEqual(self.server.requests, [])


if __name__ == "__main__":
    unittest.main()
