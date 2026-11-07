# Everyday tasks

**Bring host changes into a VM.** The VM's working copy is a git checkout,
so `git pull` works as usual. Your Mac's repository is also mounted
read-only at its host path, so commits you haven't pushed can be fetched
directly. Run this inside the VM:

```bash
git fetch /Users/<you>/Developer/preludian/myapp main
```

To copy files that are not in git, such as an edited `.env`, run
`lima-ai sync preludian/myapp feat-login`. It never deletes anything in the
VM, but it overwrites files that exist on both sides with the host's copy.
It asks first if the VM has uncommitted changes, or if the VM's repository
is on a different branch or commit than the host's.

**Refresh Claude, git or AWS config** after changing `~/.claude`,
`~/.gitconfig` or `~/.aws` on the Mac, after a new `aws sso login`, or after
running `lima-ai auth` again: `lima-ai sync-claude preludian/myapp feat-login`.

**Pause a VM** to free memory: `lima-ai stop …` and later `lima-ai start …`.

**Save and move Docker data.** Every VM has docker-backup and a folder
shared with your Mac, `/backups` in the VM and `~/Developer/backups/docker`
on the Mac. From a shell in the VM:

```bash
lima-ai shell preludian/myapp feat-login
docker compose stop
docker-backup backup --from-docker-compose compose.yaml /backups/myapp-feat-login-$(date -u +%Y%m%dT%H%M%SZ)
docker compose start
```

[Docker backups](docker-backups.md) has the restore side, the whole-daemon
variant, and how to move data to and from the Mac's Docker.

## What is copied into a VM

- **Claude config**, from `~/.claude`: `CLAUDE.md`, `RTK.md`,
  `settings.json`, `statusline-command.sh`, `skills/`, `plugins/`,
  `commands/` and `agents/`. Hooks that run files the VM won't have are
  removed. Paths under your home folder are rewritten to the VM's home;
  paths under `~/Developer` are left as they are, since the VM mounts them
  at the same place. History, sessions, caches, credentials and
  `~/.claude.json` stay on your Mac. Sessions created in the VM survive a
  `sync-claude`.
  After the copy, `lima-ai-claude-setup` runs in the VM: it marks Claude's
  onboarding as done in the VM's own `~/.claude.json`, so the token logs
  you in without the first-run wizard, and runs `rtk init -g --auto-patch`,
  which adds the rtk hook to `settings.json`, writes `RTK.md` and
  references it from `CLAUDE.md`.
- **Git config**: `~/.gitconfig` without the Mac-only parts: difftool and
  mergetool entries, the `osxkeychain` credential helper, and signing
  programs installed only on the Mac. When a signing program is removed,
  commit signing is turned off in the VM. Your global ignore file and
  `~/.ssh/known_hosts` are copied too.
- **SSH private keys**, only if you say so. The first time `new` or
  `sync-claude` finds private keys in `~/.ssh`, it lists them and asks
  whether to copy them into the VM (default: no). The answer is saved as
  `ssh_keys` under `[sync]` in `config.toml`, so you are asked once; edit
  the file to change it. Keys are recognised by their content, not their
  name, and land in the VM's `~/.ssh` with mode 600 together with their
  `.pub` files. `~/.ssh/config` is never copied, so a key with a
  non-standard name is only used when the forwarded agent holds it or you
  add a `config` entry in the VM yourself. The VM disk under `~/.lima` is
  not encrypted; `lima-ai destroy` deletes it along with the keys.
- **AWS config**, if you say yes. When `~/.aws` on the Mac has a `config`,
  a `credentials` file or SSO tokens under `sso/cache`, `new` and
  `sync-claude` ask "Copy your AWS config and SSO session (~/.aws) into the
  VM?" (default: yes); `--aws` and `--no-aws` answer without asking, and
  outside a terminal the answer is yes. Those files land in the VM's
  `~/.aws` with the folder at mode 700 and the files at 600; nothing
  already in the VM's `~/.aws` is deleted. A profile that uses SSO works
  until the copied token expires. Then either log in again on the Mac and
  run `sync-claude`, or log in inside the VM with
  `aws sso login --use-device-code`. `cli/cache` is not copied; the VM
  derives role credentials again from the token. The file is copied as is,
  so a profile whose `credential_process` runs a Mac-only program
  (aws-vault, 1Password's `op`) does not work in the VM.
- **The project**, including `.git/` and `.env*` files. Left out:
  `node_modules/`, `target/`, `.venv/`, `venv/`, `__pycache__/`, `dist/`,
  `build/`, `.next/`, `.nuxt/`, `.turbo/`, `.cache/` and `.DS_Store`.

!!! warning "Upgrading from 0.12"

    VMs cloned from a `dev-base` built by lima-ai 0.12 or earlier have no
    `aws` or `session-manager-plugin`. Run `lima-ai base --rebuild`; VMs
    created after that have both.
