# Running and recovering Holdline

Use the local supervisor for a quick lesson and the complete container stack for deployment and failure-isolation exercises. Run commands from the repository root. The application uses synthetic data and a shared service credential.

## Ports and readiness

| Service | Port | Published by the full stack |
| --- | --- | --- |
| API and desk | 8741 | 127.0.0.1 only |
| Receiving | 8742 | No |
| Policy | 8743 | No |
| Shipment | 8744 | No |
| Disposition | 8745 | No |
| Shipment MCP | 8746 | No |
| PostgreSQL | 5432 in its container | No |
| Redis | 6379 in its container | No |

The separate `docker-compose.yml` dependency setup publishes Postgres on `127.0.0.1:55432` and Redis on `127.0.0.1:63791` for Python-hosted services. Those development ports are not in the complete deployment stack.

`/health` checks the process and its local configuration. Receiving also opens its database. API `/ready` checks valid credentials, policies, fixtures, and all five service health endpoints in parallel. It returns 200 when ready and 503 otherwise. `live_configured` means the two model configuration fields are present; it is not a provider connectivity check. Queue enablement is reported separately; a broker outage is handled by the job submission route.

## Start the Python stack with Postgres and queued jobs

```bash
python scripts/setup.py
docker compose up -d --wait
```

Add these settings to your own `.env`, using its generated `POSTGRES_PASSWORD` in the URL. The setup script uses URL-safe random passwords.

```dotenv
DATABASE_URL=postgresql://holdline:YOUR_LOCAL_PASSWORD@127.0.0.1:55432/holdline
REDIS_URL=redis://127.0.0.1:63791/0
```

Then run:

```bash
python -m holdline.migrate
python run.py --worker
```

`--worker` enables the job API and starts a Celery worker explicitly. A Redis connection check fails startup if the broker is unavailable. The worker uses a thread pool for these network-bound tasks, avoiding platform-dependent process spawning behavior. Review calls have their own asynchronous deadlines; Celery process time limits are not relied on with this pool.

The supervisor checks configuration and free ports before starting children. Any child exit stops the local stack with exit 1. Ctrl+C or SIGTERM requests a clean exit 0. Logs are written under `.run/` or `HOLD_LINE_RUN_DIR`.

## Container deployment

```bash
docker compose -f compose.stack.yml up --build -d --wait
docker compose -f compose.stack.yml ps
```

Every role has its own health probe. Application containers run as UID 10001 with a read-only filesystem, a writable temporary directory, dropped capabilities, and no privilege escalation. PostgreSQL and Redis use named data volumes. Environment credentials are supplied at runtime, and the image copies an explicit set of source directories.

For a remote host with a public DNS name pointing at it, set `HOLD_LINE_DOMAIN` in `.env` and use the TLS overlay:

```bash
docker compose -f compose.stack.yml -f compose.production.yml up --build -d --wait
```

Caddy obtains the certificate and redirects HTTP to HTTPS. Ports 80 and 443 must reach the host for certificate issuance. The overlay removes the direct API port publication. Interservice traffic stays on the private container network. DNS and public certificate issuance require checks on the deployment host; local configuration validation does not prove them.

To use an image built in CI instead of building on the host, set `HOLD_LINE_IMAGE` to your registry image digest and run Compose with `--no-build` after pulling it. Preserve the same configuration and volumes during an image update.

## Migrations

`holdline/migrations.py` is the single schema authority. Version 1 upgrades legacy ledger tables with timestamps, review identity, and request fingerprints while preserving existing rows. Existing rows get `legacy-<id>` identities and their original payload. A migration-time timestamp on a legacy row is not evidence of its original creation time. Version 2 adds durable job state.

Migration transactions serialize schema updates on each supported database. Receiving applies pending migrations when opening a connection, so a new learner database works immediately. Run `python -m holdline.migrate` explicitly during an operated deployment after making a backup. Forward migration is supported; an application rollback after a future incompatible schema change requires its documented migration strategy or restoration into a separate database.

Do not delete an old database to upgrade it. Test an upgrade on a restored copy first.

## Back up and restore SQLite

The backup command uses SQLite's online backup API and runs an integrity check.

```bash
python -m holdline.backup backup .run/ledger-backup.sqlite
```

Existing backup files are never overwritten. Stop the application before switching its active ledger path. Restore into a new path, preserving the original:

```bash
HOLD_LINE_LEDGER=.run/restored-ledger.sqlite python -m holdline.backup restore .run/ledger-backup.sqlite
HOLD_LINE_LEDGER=.run/restored-ledger.sqlite python -m holdline.migrate
HOLD_LINE_LEDGER=.run/restored-ledger.sqlite python run.py
```

Verify a known review ID through the API, including its disposition, evidence snapshots, and timestamp. Backups belong outside a shared source archive. The test suite performs this round trip automatically on temporary synthetic data.

## Back up and restore Postgres

For the container stack, create a custom-format backup without copying credentials into the command:

```bash
docker compose -f compose.stack.yml exec -T postgres pg_dump -U holdline -d holdline -Fc > holdline-backup.dump
```

Check it before considering the backup complete:

```bash
docker compose -f compose.stack.yml exec -T postgres pg_restore --list < holdline-backup.dump
```

Restore into a separate database for the recovery exercise:

```bash
docker compose -f compose.stack.yml exec -T postgres createdb -U holdline holdline_restore
docker compose -f compose.stack.yml exec -T postgres pg_restore -U holdline -d holdline_restore --exit-on-error < holdline-backup.dump
```

Compare row counts and a known review payload in the restored database. Arrange backup retention and an off-host copy for a deployment you operate. Delete only the exercise database after verification; do not restore over the active database as a shortcut.

## Recover queued work

The receiving database is the status authority. Job submission first reserves a review identity, then publishes a Celery message. Database and broker commits are not atomic. If publication or the API process fails in that gap, repeat `POST /jobs` with the same body and idempotency key. This safely republishes unfinished work.

The worker acknowledges after processing, rejects work on worker loss, and retries dependency failures up to three times with bounded delay. A redelivery may repeat computation, while the ledger's identity constraint preserves one result. A saved result takes precedence over stale job state if a worker stopped after the ledger commit.

Use `GET /jobs/{review_id}` to inspect a pending, running, or failed job. Keep the original idempotency key in the submitting client. After repairing the dependency, resubmit with that key. An intentional new review uses a new key. There is no automatic scheduled sweeper; clients and operators own this explicit recovery step.

## Logs and credentials

Application events are JSON with UTC timestamps, review IDs, and event fields. API access events include request ID, path, status, and elapsed time. Authorization headers, tokens, and model keys are not logged. Evidence failures use error codes or exception class names. Specialist SDK and worker logs are separate operational logs; keep access to them limited.

Rotate `HOLD_LINE_TOKEN` by updating the secret/configuration and recreating every application service together. Rotate database credentials with the database account and receiving configuration in a coordinated maintenance window. An existing Postgres volume does not change its database password merely because its container environment changed.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Python command missing | Install Python 3.14.7; use the supported macOS/Linux or WSL2 environment |
| Port occupied | Stop the previous stack before starting another local test |
| Startup configuration failure | Run setup; check every policy setting; inspect service logs |
| 401 from a request | Use the token from the configuration that started this stack |
| `/ready` returns 503 | Inspect its checks and the named service's log |
| `/jobs` returns 409 | Use the queue-enabled stack or `run.py --worker` |
| Pending job | Start/recover the worker; inspect broker connectivity; resubmit with the original key if dispatch was interrupted |
| Model wording uses fallback | Inspect the explanation-fallback event; check provider configuration and tracing settings |
| Postgres authentication failure after editing `.env` | Update the existing database account password deliberately; recreating the container does not rotate the account |

`docker compose down` preserves data. Adding `--volumes` deletes the selected project's local volumes; use that only when deliberately discarding the exercise's data. The release scripts never include local volumes or databases.

## Dependency and release checks

Install the development lock, then run lint, formatting, tests, and `scripts/integration.py`. To validate Postgres and the queue against the dependency containers:

```bash
TEST_POSTGRES_URL="$DATABASE_URL" python -m pytest -ra
TEST_POSTGRES_URL="$DATABASE_URL" python scripts/integration.py --postgres --queue
```

Export `DATABASE_URL` in this shell first; a `.env` entry is read by the application but is not automatically a shell variable. CI constructs an explicit isolated integration URL.

The complete container acceptance check is `scripts/integration.py --external --queue` with `HOLD_LINE_TOKEN` exported from that stack. It verifies an already-running deployment without stopping its services.
