# Contributing to Holdline

Start with the README and learner guide. Open an issue in the repository where you obtained this project to report a defect, propose an exercise, or discuss a design change. Include the release version, operating system, expected result, observed result, and the smallest synthetic reproduction.

Do not attach `.env`, database files, access tokens, provider keys, or full logs containing sensitive data. Security reports follow SECURITY.md.

## Check a change

Install `requirements-dev.lock.txt` in a clean Python 3.14.7 environment, then run:

```bash
ruff check .
ruff format --check .
python -m pytest -ra
python scripts/integration.py
```

For changes to database behavior, also run the Postgres integration described in docs/operations.md. Changes to jobs or container configuration need the queue and complete-stack checks. Include the checks you ran and their outcome in the pull request.

Keep business rules separate from model wording. Preserve synthetic fixtures, evidence validation, review identity, and the no-release invariant. Add regression tests for changed behavior. Explain any new service or dependency in terms of a learner outcome or an operating need.

## Update dependencies and documents

Direct runtime dependencies live in `requirements.in`; development tools live in `requirements-dev.in`. Regenerate the locks in a fresh environment with `python scripts/update_locks.py`, then run the full checks. Review dependency changes rather than committing an unrelated environment freeze.

Edit `docs/holdline.md` as the design source. Regenerate its Word/PDF exports using the process in docs/document-exports.md, and review every rendered page. Keep API examples and the learner guide aligned with the implementation.

## Prepare a release

Update CHANGELOG.md, run the release checks, record evidence in docs/release-validation.md, then run `python scripts/package_release.py`. Share the resulting source archive rather than a copy of the working directory. Publishing the repository, tagging a release, or deploying an environment is a separate maintainer action.
