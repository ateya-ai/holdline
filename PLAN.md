# Holdline release scope

The 2.0 release delivers a local and containerized receiving review, validated A2A/MCP boundaries, evidence snapshots, idempotent ledger writes, schema upgrades, verified SQLite recovery, a durable queued workflow, CI, and a guided learner path.

The optional model writes evidence-based wording. Rules remain deterministic. Every review records release_executed as false. Human approval and warehouse execution are explicit handoff boundaries.

The supported local runtime is Python 3.14.7 on macOS and Linux, including WSL2. The complete container deployment is the reproducible hosting path. AWS CloudFormation describes the corresponding services in an existing VPC and is checked statically; deployment acceptance belongs in the owner's account.

Release acceptance is recorded in docs/release-validation.md. The executable checks, rather than this plan, determine whether a change is ready.
