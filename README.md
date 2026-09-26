# lima-ai

Run several Claude Code agents in parallel on macOS, each in its own
disposable Linux VM ([Lima](https://lima-vm.io), `vz` + `vzNAT`), each working
on one feature of a project. Every VM has its own copy of the project, its own
Docker daemon and its own network address, so the same compose app can run on
the same port side by side:

```
http://lima-dev-myapp-feat-a.local:8002
http://lima-dev-myapp-feat-b.local:8002
```

Agents get full control inside the VM (root, Docker, `claude
--dangerously-skip-permissions`) but cannot modify the host: `~/Developer` is
mounted read-only, and only the Docker backup folder is writable.

## Requirements

- macOS on Apple Silicon, Lima ≥ 2.0 (`brew install lima`)
- Claude Code on the host, with a Max subscription
- An SSH key loaded in `ssh-agent` (git in the VMs uses agent forwarding)
- `docker-backup` ≥ 0.4.0 on the host to restore VM backups into Colima
  (`brew install joepreludian/tap/docker-backup`)

## Quick start

```bash
lima-ai auth                          # once: claude setup-token, paste the token
lima-ai base                          # once: build the golden dev-base VM (several minutes)
lima-ai new preludian/myapp feat-a    # clone dev-base, copy config and project (< 1 minute)
lima-ai shell preludian/myapp feat-a  # then run `cc` (claude --dangerously-skip-permissions)
```

`<project>` is a folder relative to `~/Developer`. The VM's working copy is
`~/work/<slug>`: a normal git checkout, so `git fetch/pull/push` work
against the project's own remotes with your host identity.

## Commands

| Command | What it does |
|---|---|
| `auth [--from-stdin]` | Run `claude setup-token` and store the token in `~/.config/lima-ai/oauth-token` (mode 600) |
| `base [--rebuild]` | Build, verify and seal `dev-base` (Ubuntu 26.04, Docker, Node, Rust, Claude Code, rtk, docker-backup) |
| `template` | Print the rendered `dev-base` Lima template |
| `new <project> <feat> [--branch NAME] [--restore BACKUP] [--cpus N] [--memory X] [--disk X]` | Create a feature VM |
| `sync <project> <feat>` | Copy the host project into the VM again (never deletes; asks if the VM's copy is dirty) |
| `sync-claude <project> <feat>` | Push the Claude token, `~/.claude` subset and git config again |
| `shell <project> <feat>` | Shell in the working copy, SSH agent forwarded |
| `ls [--port N]` | Feature VMs with status, mDNS name, IP and URL |
| `start` / `stop <project> <feat>` | Start or stop a feature VM |
| `rm <project> <feat> [--yes] [--force]` | Delete a VM; lists uncommitted/unpushed work and asks again (only `--force` skips that) |
| `backup <project> <feat> [--full] [--no-images] [--no-external] [--compose-file FILE]...` | Back up the project's volumes and built images to `~/Developer/backups/docker` |
| `restore <project> <feat> <backup> [--overwrite] [--full] [--compose-file FILE]...` | Restore a backup into the VM |

Add `-v` to echo every command lima-ai runs.

## What goes into a VM

- **Claude**: the token in `~/.config/lima-ai/env`; from host `~/.claude`:
  `CLAUDE.md`, `RTK.md`, `settings.json`, `statusline-command.sh`, `skills/`,
  `plugins/`, `commands/`, `agents/`. Hooks that run host-only files are
  dropped and host home paths are rewritten to the guest home. History,
  sessions, caches and credentials stay on the host.
- **Git**: `~/.gitconfig` minus mac-only tools (difftool/mergetool,
  osxkeychain, host-only signing programs), the global excludes file and
  `~/.ssh/known_hosts`. No keys are copied.
- **Project**: an rsync of the working tree including `.git` and `.env*`,
  without `node_modules/`, `target/`, `.venv/`, `dist/`, `build/` and similar.

## Docker backups

Backups are scoped to the project's compose files (the ones `docker compose`
would load, or `--compose-file`): its named and external volumes and locally
built images. Volumes are restored under the names the restoring project
uses, so a backup made in a VM restores into the host's Colima project too.
`backup` stops the stack while it reads volumes and prints the host-side
restore commands. `restore` shows docker-backup's preview and prompt; it
never passes `--yes`. `--full` backs up the whole Docker daemon instead.

## Configuration

Optional `~/.config/lima-ai/config.toml` (unknown keys are an error):

```toml
developer_dir = "~/Developer"
backups_dir   = "~/Developer/backups/docker"
app_port      = 8002

[vm]
cpus   = 4
memory = "8GiB"
disk   = "60GiB"
ubuntu_release = "26.04"

[versions]
node_major = 24
rtk        = "0.49.0"
rtk_sha256 = "…"
docker_backup        = "0.4.0"
docker_backup_sha256 = "…"

[sync]
extra_excludes = []
```

## Development

```bash
make test        # unit tests (uv run pytest)
make test-lima   # end-to-end tests with real VMs (slow; builds dev-base if missing)
make lint        # ruff
make pex         # dist/lima-ai, a self-contained macOS arm64 executable
```
