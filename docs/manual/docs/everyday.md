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

**Refresh Claude or git config** after changing `~/.claude` or
`~/.gitconfig` on the Mac, or after running `lima-ai auth` again:
`lima-ai sync-claude preludian/myapp feat-login`.

**Pause a VM** to free memory: `lima-ai stop …` and later `lima-ai start …`.

**Save and move Docker data.** Back up the project's volumes and the images
it built locally:

```bash
lima-ai backup preludian/myapp feat-login
```

The compose stack is stopped while the volumes are read, then started
again. The backup lands in `~/Developer/backups/docker/myapp-feat-login-<UTC time>`.
lima-ai then prints the commands that restore it into your Mac's Colima.
It never runs them itself. Restore into any VM, including a new one:

```bash
lima-ai restore preludian/myapp feat-billing myapp-feat-login-20260926T141500Z
lima-ai new preludian/myapp feat-review --restore myapp-feat-login-20260926T141500Z
```

Volumes are renamed to the names the restoring project uses, so a backup
restores correctly even when the folder name differs. docker-backup shows
what it will create, overwrite or skip, and asks before it changes
anything. `--overwrite` empties and refills volumes that already exist,
after lima-ai asks its own confirmation. `backup --full` backs up the whole
Docker daemon instead of one project.

## What is copied into a VM

- **Claude config**, from `~/.claude`: `CLAUDE.md`, `RTK.md`,
  `settings.json`, `statusline-command.sh`, `skills/`, `plugins/`,
  `commands/` and `agents/`. Hooks that run files the VM won't have are
  removed. Paths under your home folder are rewritten to the VM's home;
  paths under `~/Developer` are left as they are, since the VM mounts them
  at the same place. History, sessions, caches, credentials and
  `~/.claude.json` stay on your Mac. Sessions created in the VM survive a
  `sync-claude`.
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
- **The project**, including `.git/` and `.env*` files. Left out:
  `node_modules/`, `target/`, `.venv/`, `venv/`, `__pycache__/`, `dist/`,
  `build/`, `.next/`, `.nuxt/`, `.turbo/`, `.cache/` and `.DS_Store`.
