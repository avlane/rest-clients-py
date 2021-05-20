import os
import tempfile
import unittest

from restclients import errors
from restclients.streaming import download_file
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer, blob


class StreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ApiServer().__enter__()
        cls.client = UrllibClient(base_url=cls.server.url)

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dest = os.path.join(self.tmp.name, "out.bin")

    def test_iter_bytes_in_chunks(self):
        with self.client.stream("GET", "/blob/1000") as resp:
            self.assertEqual(resp.content_length, 1000)
            chunks = list(resp.iter_bytes(300))
        self.assertEqual([len(c) for c in chunks], [300, 300, 300, 100])
        self.assertEqual(b"".join(chunks), blob(1000))

    def test_download_writes_file(self):
        written = download_file(self.client, "/blob/200000", self.dest, chunk_size=8192)
        self.assertEqual(written, 200000)
        with open(self.dest, "rb") as f:
            self.assertEqual(f.read(), blob(200000))
        self.assertFalse(os.path.exists(self.dest + ".part"))

    def test_truncated_download_is_detected_and_cleaned_up(self):
        with self.assertRaises(errors.TransportError) as ctx:
            download_file(self.client, "/blob/5000?cut=1200", self.dest)
        self.assertIn("incomplete", ctx.exception.message)
        self.assertFalse(os.path.exists(self.dest))
        self.assertFalse(os.path.exists(self.dest + ".part"))

    def test_error_status_raises_before_writing(self):
        with self.assertRaises(errors.NotFound):
            download_file(self.client, "/nothing-here", self.dest)
        self.assertFalse(os.path.exists(self.dest + ".part"))

    def test_existing_file_survives_failed_download(self):
        with open(self.dest, "wb") as f:
            f.write(b"old")
        with self.assertRaises(errors.TransportError):
            download_file(self.client, "/blob/5000?cut=10", self.dest)
        with open(self.dest, "rb") as f:
            self.assertEqual(f.read(), b"old")

    def test_stream_without_raise_exposes_error_response(self):
        with self.client.stream("GET", "/status/418", raise_for_status=False) as resp:
            self.assertEqual(resp.status, 418)
            self.assertIn(b"418", resp.read())


if __name__ == "__main__":
    unittest.main()
