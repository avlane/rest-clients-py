"""Send many records to a bulk endpoint in fixed-size batches."""
import hashlib

from restclients._compat import batched


def batch_key(job_id, index, batch):
    """Deterministic idempotency key: the same job re-run sends the same keys.

    Mixing in the batch contents means a changed batch gets a new key instead of
    being rejected (or silently replayed) as a reuse of an old one.
    """
    h = hashlib.sha256(("%s:%d:" % (job_id, index)).encode("utf-8"))
    for record in batch:
        h.update(repr(sorted(record.items()) if isinstance(record, dict) else record).encode("utf-8"))
    return h.hexdigest()[:32]


def post_in_batches(client, path, records, batch_size=100, job_id=None, wrap="items",
                    idempotency_header="Idempotency-Key"):
    """POST ``{wrap: [records...]}`` in batches and return the list of decoded responses.

    With a ``job_id`` each batch carries a deterministic idempotency key, so re-running
    a job that died half way does not re-create the batches that already succeeded
    (provided the server honours the header).
    """
    responses = []
    for index, batch in enumerate(batched(records, batch_size)):
        headers = {}
        if job_id is not None:
            headers[idempotency_header] = batch_key(job_id, index, batch)
        response = client.post(path, json={wrap: list(batch)}, headers=headers)
        responses.append(response.json())
    return responses
