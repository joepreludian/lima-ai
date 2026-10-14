# Development

```bash
make test        # unit tests; no VM or Lima install needed
make test-lima   # end-to-end tests with real VMs (a few minutes; longer if dev-base must be built)
make lint        # ruff check and format check
make build       # wheel and sdist in dist/
make pex         # dist/lima-ai, a self-contained executable for this machine's platform
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

## Releasing

GitHub Actions run `ci.yml` on every push to `main` and every pull request:
lint, unit tests on Linux and macOS, a strict manual build, and builds of the
wheel, sdist and executable on macOS arm64, Linux x86_64 and Linux arm64.
`make test-lima` does not run there, because GitHub runners cannot nest
virtual machines; run it locally before a release.

### One-time setup

Done once by the maintainer, in a browser:

1. On [pypi.org](https://pypi.org/manage/account/publishing/), add a pending
   trusted publisher for project `lima-ai` with owner `joepreludian`,
   repository `lima-ai`, workflow `release.yml` and environment `pypi`.
2. On GitHub, create an environment named `pypi` under the repository's
   Settings → Environments.

No API token is stored anywhere: the workflow authenticates to PyPI through
OIDC.

### Per release

The version lives only in `pyproject.toml`; `lima-ai --version` reads it from
the installed package.

```bash
uv version 0.2.0                 # updates pyproject.toml and uv.lock
git commit -am "chore: release 0.2.0"
git tag v0.2.0
git push origin main v0.2.0
```

The tag starts `release.yml`, which:

1. checks that the tag matches the version in `pyproject.toml`;
2. builds the wheel and sdist, and the executable on a native runner for each
   platform, packaged as `lima-ai-<version>-<target>.tar.gz` with the targets
   `aarch64-apple-darwin`, `x86_64-unknown-linux-gnu` and
   `aarch64-unknown-linux-gnu`;
3. publishes the wheel and sdist to PyPI;
4. once PyPI has the release, creates the GitHub Release with the three tarballs,
   a `SHA256SUMS` file and generated notes. A tag with a `-`, such as
   `v0.2.0-rc1`, is marked as a pre-release.

Running the workflow by hand from the Actions tab (`workflow_dispatch`) is a
dry run: everything is built and checked, nothing is published.
