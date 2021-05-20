"""Download large bodies without holding them in memory."""
import os

from restclients.errors import TransportError


def download_file(client, path, dest, params=None, headers=None, chunk_size=65536):
    """Stream ``path`` to the file ``dest`` and return the number of bytes written.

    The data goes to ``dest + ".part"`` first and is renamed only when complete,
    so a crash or dropped connection never leaves a truncated file under the
    final name. If the server declared a ``Content-Length`` and fewer bytes
    arrived, a :class:`TransportError` is raised and the partial file is removed.
    """
    partial = dest + ".part"
    written = 0
    try:
        with client.stream("GET", path, params=params, headers=headers) as resp:
            with open(partial, "wb") as out:
                for chunk in resp.iter_bytes(chunk_size):
                    out.write(chunk)
                    written += len(chunk)
            expected = resp.content_length
        if expected is not None and written != expected:
            raise TransportError("incomplete download of %s: got %d of %d bytes"
                                 % (path, written, expected), url=resp.url)
        os.replace(partial, dest)
    except BaseException:
        if os.path.exists(partial):
            os.remove(partial)
        raise
    return written
