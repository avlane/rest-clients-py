"""HttpClient on top of urllib.request (standard library only)."""
import urllib.error
import urllib.request

from restclients.client import HttpClient
from restclients.errors import TransportError
from restclients.response import Response


def socket_timeout(timeout):
    """urllib has a single socket timeout, so a (connect, read) pair becomes the larger one."""
    if isinstance(timeout, (tuple, list)):
        return max(t for t in timeout if t is not None) if any(t is not None for t in timeout) else None
    return timeout


class UrllibClient(HttpClient):
    def _send(self, method, url, headers, body, timeout):
        timeout = socket_timeout(timeout)
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return Response(resp.status, list(resp.headers.items()), resp.read(), url)
        except urllib.error.HTTPError as exc:
            # An error status is still a response; the caller decides whether to raise.
            return Response(exc.code, list(exc.headers.items()), exc.read(), url)
        except urllib.error.URLError as exc:
            raise TransportError("cannot reach %s: %s" % (url, exc.reason), url=url) from None
        except OSError as exc:
            raise TransportError("%s while talking to %s" % (exc or type(exc).__name__, url),
                                 url=url) from None
