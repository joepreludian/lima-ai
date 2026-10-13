# Development

```bash
make test        # unit tests; no VM or Lima install needed
make test-lima   # end-to-end tests with real VMs (a few minutes; longer if dev-base must be built)
make lint        # ruff check and format check
make pex         # dist/lima-ai, a self-contained macOS arm64 executable
```

`make test-lima` builds `dev-base` if it is missing, creates
`dev-limaaitest-*` VMs from a small compose project, and deletes them and
their backups when it finishes.

## Building this manual

The manual lives in `docs/manual` and is built with
[Material for MkDocs](https://squidfunk.github.io/mkdocs-material/). Read the
Docs builds it from `.readthedocs.yaml` on every push and fails the build on
any MkDocs warning, so check locally first:

```bash
make docs          # live preview at http://127.0.0.1:8000
make docs-build    # strict build, the same check Read the Docs runs
```

Both use the pinned version in `docs/manual/requirements.txt` through
`uv run --with-requirements`, so nothing is added to the project's own
dependencies.
