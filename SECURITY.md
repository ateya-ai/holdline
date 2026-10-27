# Security and supported scope

Holdline 2.0 is a learning application using synthetic shipments. Its shared bearer token represents a trusted desk or service operator; it does not identify individual users or provide per-user permissions.

Keep internal service ports private. The complete Compose stack publishes only a loopback API port. Remote hosting must use the TLS gateway or the AWS HTTPS load balancer. Rotate shared credentials when access changes and recreate all affected services. Environment changes do not update already running processes.

Rehearsal sends no data to a model provider. Live wording sends the selected synthetic findings to the configured provider. Explicitly enabled LangSmith tracing can send model inputs and outputs to that service too. Do not substitute real shipment or personal data without a separate data-handling review.

## Report a vulnerability

Use the hosting repository's private vulnerability reporting feature when available. Otherwise contact the course or repository maintainer through the channel where this project was shared and request a private reporting route. Do not post credentials or exploit details in a public issue while arranging that route.

Include the release, affected endpoint or file, a synthetic reproduction, and the impact. Only the latest published release is maintained by this project; older copies should be updated before further use.

## Before internet hosting

Use HTTPS, restrict network access, replace development credentials, verify backups and restoration, and review access logs. The provided shared-token design fits a controlled cohort or internal desk. Add an identity provider, scoped service identities, rate limits, and an authorization model when serving independent users or untrusted tenants. Model explanations are advisory; the ledger records the deterministic decision and source snapshots.
