"""multipart/form-data encoding (RFC 7578) with the standard library only.

``urllib`` has no helper for this, and it is a good thing to write once to see
what ``requests(files=...)`` and ``httpx(files=...)`` do for you: a boundary
line, per-part headers, a blank line, the bytes, repeat, and a closing boundary.
"""
import mimetypes
import os
import uuid


class FilePart:
    """A file field: ``FilePart("report.csv", b"a,b\\n1,2", "text/csv")``."""

    def __init__(self, filename, content, content_type=None):
        self.filename = filename
        self.content = content
        self.content_type = (content_type or mimetypes.guess_type(filename)[0]
                             or "application/octet-stream")

    @classmethod
    def from_path(cls, path, content_type=None):
        with open(path, "rb") as f:
            return cls(os.path.basename(path), f.read(), content_type)


def _quote(value):
    """Escape a value placed inside a quoted-string header parameter."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "%0D").replace("\n", "%0A")


def encode_multipart(fields=None, files=None, boundary=None):
    """Return ``(body, content_type)``.

    ``fields`` is a dict (or list of pairs) of text fields; ``files`` maps a
    field name to a :class:`FilePart` (or is a list of ``(name, FilePart)``).
    """
    boundary = boundary or uuid.uuid4().hex
    pairs = fields.items() if hasattr(fields, "items") else (fields or [])
    file_pairs = files.items() if hasattr(files, "items") else (files or [])
    out = []
    for name, value in pairs:
        out.append(("--%s\r\n" % boundary).encode("ascii"))
        out.append(('Content-Disposition: form-data; name="%s"\r\n\r\n' % _quote(name)).encode("utf-8"))
        out.append(str(value).encode("utf-8"))
        out.append(b"\r\n")
    for name, part in file_pairs:
        out.append(("--%s\r\n" % boundary).encode("ascii"))
        out.append(('Content-Disposition: form-data; name="%s"; filename="%s"\r\n'
                    % (_quote(name), _quote(part.filename))).encode("utf-8"))
        out.append(("Content-Type: %s\r\n\r\n" % part.content_type).encode("ascii"))
        out.append(part.content)
        out.append(b"\r\n")
    out.append(("--%s--\r\n" % boundary).encode("ascii"))
    return b"".join(out), "multipart/form-data; boundary=%s" % boundary
