# Build and verify a receiving review

Work through this guide after the README first run. You will follow one case across process boundaries, change a rule safely, recover from a failure, and prove a retry did not duplicate a write.

You should be comfortable with Python functions, JSON, a terminal, and basic HTTP requests. A2A, MCP, and Celery are introduced through their role in this application. Plan one session for the local workflow and a second for operations and queued processing; your time will depend on your familiarity with those tools.

## 1 Trace a complete review

Run `python run.py`, open the desk, and review HL-2201. Expand the audit record. Find the review ID, policy and shipment findings, policy and shipment hashes, explanation source, and ledger timestamp.

Read these files in order: `app/api.py`, `holdline/runner.py`, `specialists/protocol.py`, `holdline/executors.py`, `holdline/evidence.py`, and `holdline/ledger.py`.

A2A gives each specialist a discoverable card and a standard task/message transport. MCP exposes one typed evidence tool. Neither protocol requires the specialist's decision to come from a model. Explain why policy and shipment fetch the same record but apply different checks.

**Complete when:** you can point to the process that fetched the evidence, the function that chose the result, and the service that committed the row. Run HL-2204 and identify each blocking fact.

## 2 Change a policy safely

Inspect the five settings in `data/policies/`. Change `window_days` from 14 to 3 and run the tests. HL-2201 should now block. Update your exercise's expected case deliberately, then restore the original corpus and rerun the suite.

Try misspelling a boolean value or removing a required setting. The configuration should fail validation. A missing rule must never disable a safety check silently. Read `tests/test_policies.py` and add a boundary case of your own.

**Complete when:** you can demonstrate the 14-day inclusive boundary, the 15-day blocked boundary, and a malformed policy that fails closed. Restore the original policies before continuing.

## 3 Validate service messages

Read `holdline/contracts.py`. Every completed finding carries a role, shipment ID, review ID, source names, snapshots, and hashes. The contract checks that the verdict follows those snapshots. A review checks that both specialists used the same evidence and that the disposition follows their verdicts.

Run the runner and contract tests. Inspect the cases that inject a wrong shipment ID, a changed finding, a mismatched snapshot, and a claimed stock release.

**Complete when:** you can explain why a successful HTTP response and a recognized disposition string are insufficient to trust a result.

## 4 Observe failure and recovery

Stop the local supervisor, then run `python scripts/integration.py`. It launches services independently, interrupts policy, disposition, and receiving, and verifies recovery.

A missing policy or shipment finding produces an `INCOMPLETE` review if disposition is available. A failed disposition or ledger produces HTTP 503 without a new result. Readiness returns 503 when a required service or configuration is unavailable.

`run.py` has a different operational responsibility: if any supervised child exits, it stops the local stack and exits 1. Use independently running services or the container stack for the degraded-service exercise.

**Complete when:** you can distinguish a valid business block, incomplete evidence, and a dependency outage, and explain which ones are recorded.

## 5 Retry a write

Use the API example with one `Idempotency-Key`, then repeat it. Both requests should return the same review and ledger ID. Change the shipment while keeping the key: expect 409. Use a new key for an intentional second review.

The database enforces the review identity; the browser button alone cannot prevent a retry race. Look at the concurrent retry tests.

**Complete when:** concurrent duplicate requests create one row, while intentional reviews of the same shipment remain possible.

## 6 Migrate and recover data

Follow the SQLite backup/restore exercise in `docs/operations.md`. Restore into a new path and inspect the same review ID and evidence. Run the migration tests to see a revision-1 ledger upgraded without deleting its rows.

**Complete when:** you can recover an audit record from a verified backup and explain why deleting a database is not a migration plan.

## 7 Process a queued job

Start the container stack, submit `POST /jobs`, and poll its status URL. Stop the worker, submit another job, observe it pending, and restart the worker. Retry the submission with the same key.

Read `app/worker.py` and the queue recovery instructions. Delivery is at least once; the durable ledger identity prevents a duplicate result. The status registry is in the receiving database, not an expiring Celery result backend.

**Complete when:** a job submitted while the worker is down completes after recovery and keeps its original result on a retry.

## 8 Add optional model wording

Run the offline explanation tests before configuring a provider. They verify evidence reaches the model adapter, rehearsal never constructs a model client, and a provider failure or release claim uses the fallback.

If you have provider access, run the opt-in evaluation in `docs/evaluations.md`. Compare the live wording to the stored findings. Record the model, prompt hash, cost information available from your provider, and any unsupported claim.

**Complete when:** you can explain the difference between deterministic contract checks and evaluation of a probabilistic explanation.

## 9 Review a release

Run lint, tests, and integration from a clean copy. Build the container image and run the full stack. Package the release using `python scripts/package_release.py`; inspect its manifest and verify no `.env`, local database, or environment directory is included.

**Complete when:** another learner can follow the README without any path or credentials from your machine.

## Design discussion

For four synthetic records, one Python process would be simpler and usually preferable in a real small application. The separate services here make discovery, contracts, failures, and delivery semantics observable. Add service boundaries in your own work when ownership, independent scaling, or failure isolation justifies their operating cost.

RAG and vector search are not part of this workflow. The small policy corpus is parsed and validated directly. Add retrieval only when an evidence problem calls for it, and evaluate it as a separate change.
