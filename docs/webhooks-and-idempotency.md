# Webhooks and idempotency: notes

Both topics are about the same fact: networks fail *between* "the other side did
the work" and "I heard about it", so anything important gets delivered more than
once. The fix is to make doing it twice harmless.

## Receiving webhooks (`restclients/webhooks.py`, `signatures.py`)

1. **Verify before you parse.** Compute the HMAC over the *raw request bytes*.
   Parsing the JSON and dumping it again changes spacing and key order, and the
   signature no longer matches (there is a test for exactly this mistake).
2. **Compare in constant time** (`hmac.compare_digest`), not with `==`.
3. **Sign the timestamp too** and reject deliveries outside a window (five
   minutes here). Otherwise someone who captured one valid delivery can replay it
   forever.
4. **Allow secret rotation**: accept a list of secrets, newest first, and a
   header that may carry several `v1=` signatures.
5. **Answer quickly.** Do the slow work after responding; providers retry
   deliveries that time out, and a retry storm makes things worse.
6. **Deduplicate on the event id.** Retries mean duplicates. The receiver here
   answers 200 to a repeated `X-Event-Id` without processing it again.

The signature scheme (`t=<unix time>,v1=<hex>` over `"<t>.<body>"`) is the
common Stripe-style one. GitHub's simpler `sha256=<hex>` scheme is also
supported by `verify_github_signature`, and is checked against the example in
GitHub's documentation. Neither provider's real servers were contacted.

## Sending webhooks (`webhook_sender.py`)

* Re-sign on every attempt, so a delivery retried for longer than the receiver's
  tolerance still verifies.
* Retry 5xx, timeouts and 429; never retry other 4xx, which will not improve.
* Send a stable event id so the retried POST is safe.

## Idempotency keys (`idempotency.py`, `HttpClient(idempotency_header=...)`)

A client that times out on a POST cannot know whether it was processed. With an
`Idempotency-Key` it can send the identical request again:

* the **client** makes one key per logical call and repeats it on every retry
  (and a request carrying a key is retried even though POST normally is not);
* the **server** stores the first outcome under the key and replays it. The
  same key with a different payload is an error (422), and a key whose first
  request is still running gets 409.

`/payments?drop_response=1` on the test server processes a payment and then hangs
up without answering. The tests show one payment with a key and two without.

Bulk jobs: `post_in_batches(..., job_id=...)` derives the keys from the job id,
batch position and batch contents, so re-running a half-finished import is safe.
