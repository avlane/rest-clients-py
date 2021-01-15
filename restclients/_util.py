"""Small shared helpers."""


def is_library_error(exc, package):
    """True if ``exc`` is an instance of an exception class defined in ``package``.

    Lets a client translate another library's exceptions without importing it
    (and so without needing it installed when a session is injected).
    """
    return any(cls.__module__.split(".")[0] == package for cls in type(exc).__mro__)
