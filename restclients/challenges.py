"""Parse ``WWW-Authenticate`` headers (RFC 9110 section 11.6.1, Bearer in RFC 6750 section 3).

A header can carry several challenges, each a scheme followed by either a single
"token68" blob (``Negotiate YIIB...==``) or comma separated ``name=value`` parameters whose
values may be quoted strings. The grammar is awkward because the commas separating
parameters also separate challenges; a token followed by ``=`` is a parameter, one that is not is
the start of the next challenge.
"""
import re

_TOKEN = r"[A-Za-z0-9!#$%&'*+.^_`|~-]+"
_SCHEME = re.compile(r"\s*,?\s*(%s)" % _TOKEN)
_PARAM = re.compile(r"\s*,?\s*(%s)\s*=\s*(?:\"((?:[^\"\\]|\\.)*)\"|(%s))" % (_TOKEN, _TOKEN))
_TOKEN68 = re.compile(r"\s+([A-Za-z0-9\-._~+/]+=*)\s*(?=,|$)")


class Challenge:
    def __init__(self, scheme, params=None, token68=None):
        self.scheme = scheme.lower()
        self.params = params or {}
        self.token68 = token68

    @property
    def realm(self):
        return self.params.get("realm")

    @property
    def error(self):
        """Bearer: ``invalid_request``, ``invalid_token`` or ``insufficient_scope`` (or None)."""
        return self.params.get("error")

    @property
    def error_description(self):
        return self.params.get("error_description")

    @property
    def scope(self):
        return self.params.get("scope")

    def __repr__(self):
        return "Challenge(%r, %r)" % (self.scheme, self.params or self.token68)


def parse_www_authenticate(value):
    """List of :class:`Challenge` in the order sent; ``[]`` for a missing or unparsable header."""
    challenges = []
    if not value:
        return challenges
    pos, n = 0, len(value)
    while pos < n:
        match = _SCHEME.match(value, pos)
        if not match:
            break
        challenge = Challenge(match.group(1))
        pos = match.end()
        # either one token68 right after the scheme, or parameters
        if _PARAM.match(value, pos) is None:
            blob = _TOKEN68.match(value, pos)
            if blob:
                challenge.token68 = blob.group(1)
                pos = blob.end()
        while True:
            param = _PARAM.match(value, pos)
            if not param:
                break
            name, quoted, bare = param.groups()
            text = re.sub(r"\\(.)", r"\1", quoted) if quoted is not None else bare
            challenge.params.setdefault(name.lower(), text)
            pos = param.end()
        challenges.append(challenge)
        if pos < n and value[pos:].strip() == "":
            break
    return challenges


def find_challenge(value, scheme):
    """The first challenge using ``scheme`` (case-insensitive), or None."""
    scheme = scheme.lower()
    for challenge in parse_www_authenticate(value):
        if challenge.scheme == scheme:
            return challenge
    return None
