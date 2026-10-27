# API examples and contracts

The API listens on port 8741. Read and write routes require `Authorization: Bearer <token>`. The HTML desk, `/health`, and `/ready` are public. Specialist discovery cards and service health checks are also public. The API's `/openapi.json` schema requires the token; interactive framework documentation is disabled.

## Prepare the terminal

From the activated environment at the repository root, load only the token into a shell variable:

```bash
export HOLD_LINE_TOKEN="$(python -c 'from holdline.config import token; print(token())')"
```

Keep the token out of URLs, screenshots, commits, and shared output. Shell examples use the local HTTP endpoint; use HTTPS for a remote host.

## Run a review and retry it

```bash
curl --fail-with-body -sS http://127.0.0.1:8741/cases \
  -H "Authorization: Bearer $HOLD_LINE_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: lesson-review-001' \
  -d '{"shipment_id":"HL-2201","mode":"rehearsal"}'
```

Repeat this command to retrieve the original result. It contains `review`, `posted`, `replayed`, and `ledger`. The review contains findings and their evidence snapshots; the ledger includes `id`, `review_id`, `shipment_id`, `disposition`, and `created_at`.

An idempotency key is 8–128 letters, digits, dots, colons, underscores, or hyphens. It identifies one shipment/mode request. Reusing it for a different shipment or mode returns 409. Omit it only when you intend each request to be a new review; the response's `X-Review-ID` header identifies that review. Retry a failed keyed request using the same key. A deliberate new review gets a new key.

The review deadline is 55 seconds. Clients should allow at least 65 seconds and treat a lost response as an unknown outcome until they retry or query the saved review. Do not generate a new key merely because a request timed out.

## Read an audit record

`GET /reviews/{review_id}` retrieves the original saved payload. `GET /ledger?after=0&limit=20` returns ordered rows and `next_after`. Pass that value as `after` to continue. The page limit is 1–100. Retain a page of results only as long as your own use requires.

## Submit a job

The complete container stack enables this route. For the Python supervisor, run with `--worker` after starting Redis.

```bash
curl --fail-with-body -sS http://127.0.0.1:8741/jobs \
  -H "Authorization: Bearer $HOLD_LINE_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: lesson-queued-001' \
  -d '{"shipment_id":"HL-2204","mode":"rehearsal"}'
```

A successful submission returns 202, `review_id`, and `status_url`. Request that status URL with the same authorization header. States are `pending`, `running`, `complete`, and `failed`. A completed response contains the original ledger row in `result`. Unknown job IDs return 404.

The job registry is committed before broker publication. If publication fails, the API returns 503 and preserves the pending job. If the API stops in the gap between those operations, resubmitting the same request with the same key safely publishes it again. This is an explicit recovery protocol, not a claim of atomic database/broker delivery. Operators should investigate old pending/running jobs and resubmit them with their original key after recovery.

## Error meanings

| Status | Meaning | Response |
| --- | --- | --- |
| 400 | Malformed idempotency key or review ID | Correct the request |
| 401 | Missing or incorrect token | Check the local configuration |
| 404 | Unknown shipment, review, or job | Check the identifier |
| 409 | Key conflict, unavailable live configuration, or disabled queue path | Use the original request or correct the configuration |
| 422 | Body failed schema or evidence validation | Inspect the contract; do not retry unchanged |
| 503 | Dependency unavailable or review deadline exceeded | Recover the dependency; retry with the same key |

A known policy block is HTTP 200 with `BLOCKED`. Missing policy/shipment evidence can be HTTP 200 with `INCOMPLETE`; it is still a recorded review. A failed disposition or receiving call produces 503. Model wording failures use a labelled fallback without changing the decision.

The receiving and specialist endpoints are internal service contracts. A shared service token is appropriate for this controlled teaching deployment. A product serving distinct users needs an identity and authorization design before exposing those internal services.
