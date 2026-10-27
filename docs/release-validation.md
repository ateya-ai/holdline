# Holdline 2.0 release validation

Release date: 26 October 2026. This acceptance record covers the source release and the locally exercised deployments.

## Verified

| Check | Evidence |
| --- | --- |
| Clean Python installation | The source archive is installed into a new Python 3.14.7 environment and checked using its own dependency lock |
| Code checks | Ruff lint and formatting checks pass; dependency consistency check passes |
| Regression suite | 79 tests pass with the explicit Postgres URL; the clean default run passes 77 with two Postgres checks skipped. Coverage includes policy validation, all verdict combinations, message tampering, retry identity, concurrent writes, authentication, readiness, migration, backup/restore, model adapter, setup, document freshness, and packaging |
| SQLite service integration | Real A2A/MCP calls for all four shipments, concurrent requests, outages, and recovery |
| Postgres integration | The same case flow and retry checks, plus legacy Postgres migration and durable jobs |
| Queue behavior | A job submitted with no worker running completes after the worker starts; resubmission returns the saved result |
| Supervisor | Smoke check succeeds; SIGTERM exits 0; an MCP child crash exits 1; listeners are cleaned up |
| Full container deployment | All nine services become healthy; the public API and real queued workflow pass the acceptance script |
| Image builds | Application images build for native ARM64 and Linux AMD64 |
| Recovery | SQLite backup/restore round trip passes; a custom-format Postgres backup restores into a separate database with the same row count |
| TLS configuration | Compose production overlay parses and Caddy validates its configuration |
| AWS definition | Complete CloudFormation stack passes cfn-lint 1.58.0 |
| Python runtime dependency audit | pip-audit 2.10.1 reports no known vulnerabilities after updating certifi and opentelemetry-api |
| Design exports | Four-page Word/PDF design note rendered and visually reviewed; source/export hashes recorded |
| Browser desk | Rehearsal, saved-result retry, blocked shipment, and readable evidence verified in the browser |
| Source archive | 93 source files; manifest hashes verified; local configuration, databases, virtual environments, Git metadata, and caches excluded |

The runtime audit used the published advisory database at release preparation time. It is a point-in-time dependency check, not a guarantee against future disclosures. The patched packages address the [certifi advisory](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2) and [OpenTelemetry advisory](https://github.com/open-telemetry/opentelemetry-python/security/advisories/GHSA-xcq7-p3pf-p88h).

## Repeat the checks

```bash
python -m pip install -r requirements-dev.lock.txt
python -m pip check
ruff check .
ruff format --check .
python -m pytest -ra
python scripts/integration.py
python scripts/check_supervisor.py
```

With the dependency containers started and an explicit test database URL:

```bash
TEST_POSTGRES_URL="$DATABASE_URL" python -m pytest -ra
TEST_POSTGRES_URL="$DATABASE_URL" python scripts/integration.py --postgres --queue
```

For the container stack, export its access token and run:

```bash
python scripts/integration.py --external --queue
```

Build and verify the source release:

```bash
python scripts/package_release.py
python scripts/verify_release.py dist/holdline-2.0.0.zip --run-checks
```

Infrastructure and dependency checks use the separate tooling requirements:

```bash
python -m pip install -r requirements-infra.txt
cfn-lint aws/cloudformation/stack.json
pip-audit -r requirements.lock.txt --no-deps --disable-pip
```

## External acceptance

The GitHub Actions workflow is included; hosted workflow runs occur after the repository is pushed to its hosting service. Local checks do not represent a hosted Actions run.

AWS resources have not been deployed during this release preparation. Regional engine availability, quotas, network egress, DNS, certificates, and rollout health are deployment-account acceptance checks described in aws/README.md. Public DNS certificate issuance is likewise checked on the chosen TLS host.

Paid model calls have not been made. Offline adapter tests pass, and the explicit opt-in evaluation script is included for a maintainer with provider access. Live model prose requires the grounding review described in docs/evaluations.md.

The source is prepared for sharing with learners. Production use with real users, identities, and shipment data requires the product-specific decisions described in SECURITY.md.
