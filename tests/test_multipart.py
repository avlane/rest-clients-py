import hashlib
import unittest

from restclients.multipart import FilePart, encode_multipart
from restclients.urllib_client import UrllibClient
from tests.server import ApiServer


class EncodeTests(unittest.TestCase):
    def test_exact_layout(self):
        body, ctype = encode_multipart({"title": "Q1"}, {"doc": FilePart("a.txt", b"hi", "text/plain")},
                                       boundary="XX")
        self.assertEqual(ctype, "multipart/form-data; boundary=XX")
        self.assertEqual(body, (
            b'--XX\r\nContent-Disposition: form-data; name="title"\r\n\r\nQ1\r\n'
            b'--XX\r\nContent-Disposition: form-data; name="doc"; filename="a.txt"\r\n'
            b'Content-Type: text/plain\r\n\r\nhi\r\n'
            b'--XX--\r\n'))

    def test_random_boundary_differs(self):
        self.assertNotEqual(encode_multipart({"a": 1})[1], encode_multipart({"a": 1})[1])

    def test_content_type_guessed_from_filename(self):
        self.assertEqual(FilePart("data.json", b"{}").content_type, "application/json")
        self.assertEqual(FilePart("blob.unknownext", b"").content_type, "application/octet-stream")

    def test_quotes_and_newlines_in_names_are_escaped(self):
        body, _ = encode_multipart({}, {"f": FilePart('we"ird\r\n.txt', b"")}, boundary="B")
        self.assertIn(b'filename="we\\"ird%0D%0A.txt"', body)


class UploadToServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ApiServer().__enter__()
        cls.client = UrllibClient(base_url=cls.server.url)

    @classmethod
    def tearDownClass(cls):
        cls.server.__exit__(None, None, None)

    def upload(self, fields=None, files=None):
        body, ctype = encode_multipart(fields, files)
        resp = self.client.post("/upload", data=body, headers={"Content-Type": ctype})
        return resp.json()["parts"]

    def test_server_parses_what_we_encode(self):
        content = bytes(range(256)) * 40  # binary, includes CR, LF and quote bytes
        parts = self.upload({"title": "caf\u00e9", "n": 3},
                            {"upload": FilePart("blob.bin", content, "application/x-custom")})
        by_name = {p["name"]: p for p in parts}
        self.assertEqual(by_name["title"]["text"], "caf\u00e9")
        self.assertEqual(by_name["n"]["text"], "3")
        self.assertEqual(by_name["upload"]["filename"], "blob.bin")
        self.assertEqual(by_name["upload"]["content_type"], "application/x-custom")
        self.assertEqual(by_name["upload"]["size"], len(content))
        self.assertEqual(by_name["upload"]["sha256"], hashlib.sha256(content).hexdigest())

    def test_multiple_files_with_same_field_name(self):
        parts = self.upload(None, [("f", FilePart("a.txt", b"A")), ("f", FilePart("b.txt", b"BB"))])
        self.assertEqual([(p["filename"], p["size"]) for p in parts], [("a.txt", 1), ("b.txt", 2)])

    def test_server_rejects_non_multipart(self):
        from restclients.errors import ClientError
        with self.assertRaises(ClientError):
            self.client.post("/upload", json={"a": 1})


if __name__ == "__main__":
    unittest.main()
