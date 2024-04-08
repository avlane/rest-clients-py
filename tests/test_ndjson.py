import unittest

from restclients import errors
from restclients.response import IterReader, StreamResponse
from restclients.streaming import iter_lines, iter_ndjson
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


def stream_of(*chunks):
    return StreamResponse(200, {}, IterReader(chunks))


class IterLinesTests(unittest.TestCase):
    def test_lines_across_chunk_boundaries(self):
        self.assertEqual(list(iter_lines(stream_of(b"ab", b"c\nde", b"f\n", b"g"))),
                         [b"abc", b"def", b"g"])

    def test_crlf_split_between_chunks(self):
        self.assertEqual(list(iter_lines(stream_of(b"one\r", b"\ntwo\r\n"))), [b"one", b"two"])

    def test_blank_lines_and_trailing_newline(self):
        self.assertEqual(list(iter_lines(stream_of(b"a\n\nb\n"))), [b"a", b"", b"b"])

    def test_empty_stream(self):
        self.assertEqual(list(iter_lines(stream_of())), [])

    def test_small_chunk_size_on_one_big_chunk(self):
        self.assertEqual(list(iter_lines(stream_of(b"x" * 10 + b"\n" + b"y" * 3), chunk_size=3)),
                         [b"x" * 10, b"y" * 3])


class NdjsonAgainstServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ApiServer().__enter__()
        cls.client = UrllibClient(base_url=cls.server.url)

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def rows(self, **params):
        return list(iter_ndjson(self.client, "/ndjson", params=params))

    def test_streams_every_object(self):
        rows = self.rows(count=5)
        self.assertEqual([r["n"] for r in rows], [1, 2, 3, 4, 5])
        self.assertEqual(rows[2]["name"], "row-3")

    def test_it_is_lazy(self):
        stream = iter_ndjson(self.client, "/ndjson", params={"count": 50, "delay": 0.01})
        self.assertEqual(next(stream)["n"], 1)
        stream.close()                      # abandoning the stream closes the connection

    def test_blank_lines_crlf_and_one_byte_chunks(self):
        self.assertEqual(len(self.rows(count=4, blank=1)), 4)
        self.assertEqual(len(self.rows(count=4, crlf=1)), 4)
        self.assertEqual([r["n"] for r in self.rows(count=3, split=1)], [1, 2, 3])

    def test_bad_line_names_its_number(self):
        seen = []
        with self.assertRaises(errors.ApiError) as ctx:
            for row in iter_ndjson(self.client, "/ndjson", params={"count": 5, "bad": 3}):
                seen.append(row["n"])
        self.assertEqual(seen, [1, 2])
        self.assertIn("line 3", ctx.exception.message)
        self.assertEqual(ctx.exception.body, b"{oops")

    def test_truncated_stream_is_a_transport_error(self):
        seen = []
        with self.assertRaises(errors.TransportError):
            for row in iter_ndjson(self.client, "/ndjson", params={"count": 10, "fail_after": 4}):
                seen.append(row["n"])
        self.assertEqual(seen, [1, 2, 3, 4])

    def test_error_status_before_streaming(self):
        with self.assertRaises(errors.NotFound):
            list(iter_ndjson(self.client, "/missing-stream"))

    def test_accept_header(self):
        self.rows(count=1)
        self.assertIn("ndjson", self.server.requests[-1][2]["Accept"])


if __name__ == "__main__":
    unittest.main()
