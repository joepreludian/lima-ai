# Installation

## Requirements

- macOS on Apple Silicon
- [Lima](https://lima-vm.io) 2.0 or later: `brew install lima`
- Rosetta, for running `linux/amd64` images:
  `softwareupdate --install-rosetta --agree-to-license`
- Claude Code on the Mac, signed in with a Max subscription
- An SSH key loaded in `ssh-agent`, so git over SSH works in the VMs
- [uv](https://docs.astral.sh/uv/), to install lima-ai from source
- Optional: [docker-backup](https://docker-backup.readthedocs.io) 0.4.0 or
  later, to restore VM backups into the Mac's Colima:
  `brew install joepreludian/tap/docker-backup`

## Installation

From a checkout of this repository, either install it as a uv tool:

```bash
uv tool install .
```

or build a single self-contained executable and put it on your `PATH`:

```bash
make pex                         # writes dist/lima-ai
cp dist/lima-ai ~/.local/bin/
```

Check it with `lima-ai --version`, then follow the [Quickstart](quickstart.md).
