"""The plain standard-library way: urllib.request plus json.

Everything later in the package is a refinement of this one function.
"""
import json
import urllib.request


def get_json(url, timeout=10):
    """GET ``url`` and return the decoded JSON body."""
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
    return json.loads(raw.decode(charset))
