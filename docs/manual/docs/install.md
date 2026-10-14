# Installation

## Requirements

- macOS on Apple Silicon
- [Lima](https://lima-vm.io) 2.0 or later: `brew install lima`
- Rosetta, for running `linux/amd64` images:
  `softwareupdate --install-rosetta --agree-to-license`
- Claude Code on the Mac, signed in with a Max subscription
- An SSH key loaded in `ssh-agent`, so git over SSH works in the VMs
- [uv](https://docs.astral.sh/uv/) (or pipx), to install lima-ai from PyPI or from source
- Optional: [docker-backup](https://docker-backup.readthedocs.io) 0.4.0 or
  later, to restore VM backups into the Mac's Colima:
  `brew install joepreludian/tap/docker-backup`

## Installation

### From PyPI (recommended)

```bash
uv tool install lima-ai
```

Upgrade later with `uv tool upgrade lima-ai`. With
[pipx](https://pipx.pypa.io) instead: `pipx install lima-ai` and
`pipx upgrade lima-ai`.

### Executable from GitHub Releases

Each [release](https://github.com/joepreludian/lima-ai/releases) carries a
self-contained executable that needs no Python, for three platforms:

| Platform | File |
|---|---|
| macOS, Apple Silicon | `lima-ai-<version>-aarch64-apple-darwin.tar.gz` |
| Linux, x86_64 | `lima-ai-<version>-x86_64-unknown-linux-gnu.tar.gz` |
| Linux, arm64 | `lima-ai-<version>-aarch64-unknown-linux-gnu.tar.gz` |

Download the file for your platform and `SHA256SUMS` from the release page,
then (shown for macOS; substitute your platform's name):

```bash
shasum -a 256 --ignore-missing -c SHA256SUMS
tar -xzf lima-ai-<version>-aarch64-apple-darwin.tar.gz
cp lima-ai-<version>-aarch64-apple-darwin/lima-ai ~/.local/bin/
```

!!! note "The macOS executable is not signed"
    macOS Gatekeeper blocks the first run of an unsigned executable downloaded
    from the internet. Clear the quarantine flag once:

    ```bash
    xattr -d com.apple.quarantine ~/.local/bin/lima-ai
    ```

### From source

From a checkout of this repository, either install it as a uv tool:

```bash
uv tool install .
```

or build a single self-contained executable and put it on your `PATH`:

```bash
make pex                         # writes dist/lima-ai
cp dist/lima-ai ~/.local/bin/
```

Check it with `lima-ai --version`, run `lima-ai doctor` to see what is still
missing, then follow the [Quickstart](quickstart.md).
