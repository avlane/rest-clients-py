"""Download large bodies without holding them in memory."""
import os
import re

from restclients.errors import TransportError, error_for_status

_CONTENT_RANGE = re.compile(r"bytes (\d+)-(\d+)/(\d+|\*)")
_UNSATISFIED = re.compile(r"bytes \*/(\d+)")


def download_file(client, path, dest, params=None, headers=None, chunk_size=65536, resume=False):
    """Stream ``path`` to the file ``dest`` and return the size of the finished file.

    The data goes to ``dest + ".part"`` first and is renamed only when complete,
    so a crash or dropped connection never leaves a truncated file under the
    final name. If the server declared a ``Content-Length`` and fewer bytes
    arrived, a :class:`TransportError` is raised.

    With ``resume=True`` an existing ``.part`` file is continued using a
    ``Range`` request, and a failed download leaves the ``.part`` file in place
    for the next attempt. If the server ignores ``Range`` and answers 200, the
    download starts over.
    """
    partial = dest + ".part"
    offset = os.path.getsize(partial) if resume and os.path.exists(partial) else 0
    send_headers = dict(headers or {})
    if offset:
        send_headers["Range"] = "bytes=%d-" % offset
    try:
        with client.stream("GET", path, params=params, headers=send_headers,
                           raise_for_status=False) as resp:
            if resp.status == 416 and offset:
                # The partial file may already be the whole thing.
                match = _UNSATISFIED.match(resp.headers.get("Content-Range", ""))
                if match and int(match.group(1)) == offset:
                    os.replace(partial, dest)
                    return offset
                offset = 0
                os.remove(partial)
                return download_file(client, path, dest, params, headers, chunk_size, resume)
            if resp.status >= 400:
                raise error_for_status(resp.status, resp.url, resp.read(), resp.headers.as_dict())
            mode = "wb"
            expected = resp.content_length
            if resp.status == 206:
                match = _CONTENT_RANGE.match(resp.headers.get("Content-Range", ""))
                if not match or int(match.group(1)) != offset:
                    raise TransportError("server answered with an unexpected Content-Range",
                                         url=resp.url)
                mode = "ab"
                expected = offset + expected if expected is not None else None
            else:
                offset = 0  # full response: whatever was in the .part file is stale
            written = offset
            with open(partial, mode) as out:
                for chunk in resp.iter_bytes(chunk_size):
                    out.write(chunk)
                    written += len(chunk)
        if expected is not None and written != expected:
            raise TransportError("incomplete download of %s: got %d of %d bytes"
                                 % (path, written, expected), url=resp.url)
        os.replace(partial, dest)
    except BaseException:
        if not resume and os.path.exists(partial):
            os.remove(partial)
        raise
    return written


def iter_lines(stream, chunk_size=4096):
    """Yield the lines of a :class:`StreamResponse` body as bytes, without line endings.

    Chunk boundaries fall anywhere, including between the ``\\r`` and ``\\n`` of one
    line ending, so incomplete tails are carried over to the next chunk. A final
    line without a trailing newline is still yielded.
    """
    pending = b""
    for chunk in stream.iter_bytes(chunk_size):
        pending += chunk
        *lines, pending = pending.split(b"\n")
        for line in lines:
            yield line[:-1] if line.endswith(b"\r") else line
    if pending:
        yield pending[:-1] if pending.endswith(b"\r") else pending


def iter_ndjson(client, path, params=None, headers=None, chunk_size=4096):
    """Stream a newline-delimited JSON (NDJSON / JSON Lines) response, one object at a time.

    Blank lines are skipped. A line that is not valid JSON raises ``ApiError`` that names
    the line number; the connection is closed when the generator is closed or exhausted.
    """
    from restclients.errors import ApiError
    import json

    headers = dict(headers or {})
    headers.setdefault("Accept", "application/x-ndjson, application/json")
    with client.stream("GET", path, params=params, headers=headers) as resp:
        for number, line in enumerate(iter_lines(resp, chunk_size), 1):
            if not line.strip():
                continue
            try:
                yield json.loads(line.decode("utf-8"))
            except ValueError:
                raise ApiError("line %d of the stream is not valid JSON" % number,
                               url=resp.url, body=line) from None
