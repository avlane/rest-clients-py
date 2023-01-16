"""Read an OpenAPI 3 description into plain Python objects.

Only JSON documents are read (YAML needs a third-party parser, and this repo
sticks to the standard library). The model is deliberately small: the
operations of the API with their parameters, request body and response schemas,
and the component schemas. It is the input to the code generator in
``openapi_gen``.
"""
import json
import re

from restclients.errors import ApiError

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


class SpecError(ApiError):
    """The document is not a usable OpenAPI description."""


class Parameter:
    def __init__(self, name, location, required, schema, description=""):
        self.name = name
        self.location = location            # "path", "query", "header" or "cookie"
        self.required = required or location == "path"
        self.schema = schema or {}
        self.description = description

    def __repr__(self):
        return "Parameter(%s in %s%s)" % (self.name, self.location, ", required" if self.required else "")


class Operation:
    def __init__(self, operation_id, method, path, summary, tags, parameters, request_body, responses):
        self.operation_id = operation_id
        self.method = method.upper()
        self.path = path
        self.summary = summary
        self.tags = tags
        self.parameters = parameters
        self.request_body = request_body      # {"required": bool, "schema": {...}} or None
        self.responses = responses            # {"200": schema-or-None, ...}

    @property
    def success_schema(self):
        """Schema of the first 2xx response that has one, else None."""
        for status in sorted(self.responses):
            if status.startswith("2") and self.responses[status] is not None:
                return self.responses[status]
        return None

    def __repr__(self):
        return "Operation(%s %s %s)" % (self.operation_id, self.method, self.path)


class OpenApiSpec:
    def __init__(self, title, version, base_url, operations, schemas):
        self.title = title
        self.version = version
        self.base_url = base_url
        self.operations = operations
        self.schemas = schemas                # name -> schema dict ($refs kept)

    def operation(self, operation_id):
        for op in self.operations:
            if op.operation_id == operation_id:
                return op
        raise KeyError(operation_id)


def load_spec(source):
    """Load from a path, a JSON string, or an already-decoded dict."""
    if isinstance(source, dict):
        document = source
    else:
        text = source
        if not source.lstrip().startswith("{"):
            try:
                with open(source, encoding="utf-8") as f:
                    text = f.read()
            except OSError as exc:
                raise SpecError("cannot read %s: %s" % (source, exc.strerror or exc)) from None
        try:
            document = json.loads(text)
        except ValueError as exc:
            raise SpecError("not valid JSON (YAML specs are not supported): %s" % exc) from None
    return parse_spec(document)


def resolve_ref(document, ref):
    """Follow a local ``#/a/b/c`` reference."""
    if not ref.startswith("#/"):
        raise SpecError("only local references are supported, got %r" % ref)
    node = document
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            raise SpecError("unresolvable reference %r" % ref)
        node = node[part]
    return node


def _deref(document, node):
    """Replace a top-level ``{"$ref": ...}`` with its target (repeatedly)."""
    seen = 0
    while isinstance(node, dict) and "$ref" in node:
        node = resolve_ref(document, node["$ref"])
        seen += 1
        if seen > 20:
            raise SpecError("reference loop")
    return node


def _json_schema(document, content):
    """Schema for the JSON media type of a request/response ``content`` map."""
    for media, body in (content or {}).items():
        if media.split(";")[0].strip().lower() in ("application/json", "application/*+json"):
            return body.get("schema")
    return None


def _operation_id(method, path):
    words = re.sub(r"[{}]", "", path).strip("/").replace("/", "_").replace("-", "_")
    return "%s_%s" % (method, words or "root")


def parse_spec(document):
    if not isinstance(document, dict) or not str(document.get("openapi", "")).startswith("3."):
        raise SpecError("expected an OpenAPI 3.x document (missing 'openapi: 3.x')")
    info = document.get("info", {})
    servers = document.get("servers") or [{"url": ""}]
    operations = []
    for path, item in (document.get("paths") or {}).items():
        item = _deref(document, item)
        shared = [_deref(document, p) for p in item.get("parameters", [])]
        for method in HTTP_METHODS:
            if method not in item:
                continue
            op = item[method]
            own = [_deref(document, p) for p in op.get("parameters", [])]
            merged = {(p["name"], p["in"]): p for p in shared}
            merged.update({(p["name"], p["in"]): p for p in own})   # operation level overrides path level
            parameters = [Parameter(p["name"], p["in"], p.get("required", False), p.get("schema"),
                                    p.get("description", "")) for p in merged.values()]
            body = _deref(document, op.get("requestBody")) if op.get("requestBody") else None
            request_body = None
            if body is not None:
                request_body = {"required": body.get("required", False),
                                "schema": _json_schema(document, body.get("content"))}
            responses = {}
            for status, response in (op.get("responses") or {}).items():
                response = _deref(document, response)
                responses[str(status)] = _json_schema(document, response.get("content"))
            operations.append(Operation(op.get("operationId") or _operation_id(method, path), method,
                                        path, op.get("summary", ""), op.get("tags", []), parameters,
                                        request_body, responses))
    ids = [o.operation_id for o in operations]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise SpecError("duplicate operationId: %s" % ", ".join(duplicates))
    schemas = (document.get("components") or {}).get("schemas") or {}
    return OpenApiSpec(info.get("title", ""), info.get("version", ""), servers[0].get("url", ""),
                       operations, schemas)
