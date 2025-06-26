"""Storing bodies in JSON: text when it is UTF-8, base64 otherwise."""
import base64


def encode_body(body):
    """JSON-friendly form of a body: ``{"text": ...}`` when it is UTF-8, else base64."""
    if not body:
        return {"text": ""}
    try:
        return {"text": body.decode("utf-8")}
    except UnicodeDecodeError:
        return {"base64": base64.b64encode(body).decode("ascii")}


def decode_body(stored):
    if "base64" in stored:
        return base64.b64decode(stored["base64"])
    return stored.get("text", "").encode("utf-8")
