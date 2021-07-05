import os
import tempfile
import unittest

from restclients import errors
from restclients.httpx_client import HttpxClient
from restclients.requests_client import RequestsClient
from restclients.response import IterReader
from restclients.streaming import download_file
from restclients.testing import FakeResponse, FakeSession


class IterReaderTests(unittest.TestCase):
    def test_reads_across_chunk_boundaries(self):
        reader = IterReader([b"ab", b"cde", b"f"])
        self.assertEqual([reader.read(4), reader.read(4), reader.read(4)], [b"abcd", b"ef", b""])

    def test_read_all_and_close(self):
        closed = []
        reader = IterReader([b"xy", b"z"], lambda: closed.append(1))
        self.assertEqual(reader.read(), b"xyz")
        reader.close()
        self.assertEqual(closed, [1])


class StreamingWithFakesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dest = os.path.join(self.tmp.name, "f.bin")

    def check_download(self, client, session):
        written = download_file(client, "http://api.test/file", self.dest, chunk_size=7)
        self.assertEqual(written, 26)
        with open(self.dest, "rb") as f:
            self.assertEqual(f.read(), b"abcdefghijklmnopqrstuvwxyz")
        return session.calls[0]

    def payload(self, **kwargs):
        headers = {"Content-Length": "26"}
        headers.update(kwargs)
        return FakeResponse(200, b"abcdefghijklmnopqrstuvwxyz", headers)

    def test_requests_client_streams_with_stream_true(self):
        session = FakeSession([self.payload()])
        call = self.check_download(RequestsClient(session), session)
        self.assertTrue(call["stream"])

    def test_httpx_client_streams(self):
        session = FakeSession([self.payload()])
        self.check_download(HttpxClient(session), session)

    def test_truncated_body_is_detected(self):
        session = FakeSession([FakeResponse(200, b"short", {"Content-Length": "26"})])
        with self.assertRaises(errors.TransportError):
            download_file(RequestsClient(session), "http://api.test/file", self.dest)
        self.assertFalse(os.path.exists(self.dest + ".part"))

    def test_error_status_raises(self):
        session = FakeSession([FakeResponse(404, json={"error": "gone"})])
        with self.assertRaises(errors.NotFound):
            download_file(HttpxClient(session), "http://api.test/file", self.dest)


if __name__ == "__main__":
    unittest.main()
