"""Convenience wrappers for uploading files."""
from restclients.multipart import FilePart


def upload_file(client, path, filepath, field="file", fields=None, method="POST", content_type=None):
    """Upload one file from disk as multipart/form-data and return the response.

    The whole file is read into memory; for very large files use a streaming
    upload (``data=`` with an iterator) with a transport that supports it.
    """
    part = FilePart.from_path(filepath, content_type)
    return client.request(method, path, files={field: part}, form=fields)


def upload_many(client, path, filepaths, field="files", fields=None):
    """Upload several files under one field name (``files[]`` style APIs)."""
    pairs = [(field, FilePart.from_path(p)) for p in filepaths]
    return client.request("POST", path, files=pairs, form=fields)
