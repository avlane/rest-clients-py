import asyncio
import hashlib
import os
import tempfile
import unittest

from restclients.async_client import ThreadedAsyncClient
from restclients.multipart import FilePart
from restclients.requests_client import RequestsClient
from restclients.testing import FakeSession
from restclients.uploads import upload_file, upload_many
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


class UploadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ApiServer().__enter__()
        cls.client = UrllibClient(base_url=cls.server.url)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.paths = []
        for name, data in (("a.csv", b"x,y\n1,2\n"), ("b.bin", os.urandom(5000))):
            path = os.path.join(cls.tmp.name, name)
            with open(path, "wb") as f:
                f.write(data)
            cls.paths.append((path, data))

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)
        cls.tmp.cleanup()

    def test_upload_file_with_fields(self):
        path, data = self.paths[0]
        parts = upload_file(self.client, "/upload", path, field="doc", fields={"kind": "csv"}).json()["parts"]
        by_name = {p["name"]: p for p in parts}
        self.assertEqual(by_name["kind"]["text"], "csv")
        self.assertEqual(by_name["doc"]["filename"], "a.csv")
        self.assertEqual(by_name["doc"]["content_type"], "text/csv")
        self.assertEqual(by_name["doc"]["sha256"], hashlib.sha256(data).hexdigest())

    def test_upload_many(self):
        parts = upload_many(self.client, "/upload", [p for p, _ in self.paths]).json()["parts"]
        self.assertEqual([p["filename"] for p in parts], ["a.csv", "b.bin"])
        self.assertEqual(parts[1]["size"], 5000)

    def test_files_given_as_tuples(self):
        resp = self.client.post("/upload", files={"f": ("n.txt", b"hello", "text/plain")})
        self.assertEqual(resp.json()["parts"][0]["size"], 5)

    def test_async_client_uploads_too(self):
        client = ThreadedAsyncClient(UrllibClient(base_url=self.server.url))
        resp = asyncio.run(client.post("/upload", files={"f": FilePart("z.txt", b"zz")}))
        self.assertEqual(resp.json()["parts"][0]["filename"], "z.txt")

    def test_requests_client_sends_multipart_body_to_the_session(self):
        session = FakeSession()
        RequestsClient(session).post("http://api.test/up", files={"f": ("n.txt", b"hello")},
                                     form={"a": "1"})
        call = session.calls[0]
        self.assertTrue(call["headers"]["Content-Type"].startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="a"', call["data"])
        self.assertIn(b"hello", call["data"])


if __name__ == "__main__":
    unittest.main()
