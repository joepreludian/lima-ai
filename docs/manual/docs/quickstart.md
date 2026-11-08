# Quickstart

This walk-through runs two workspaces of the project at
`~/Developer/preludian/myapp` side by side. Substitute your own project path:
it is always a folder relative to `~/Developer`.

### 1. Install lima-ai (once)

```bash
uv tool install lima-ai      # or: brew install joepreludian/tap/lima-ai
```

The [Installation](install.md) page lists the requirements and the other
ways to install, including a self-contained executable with no Python.

### 2. Check the dependencies

```bash
lima-ai doctor
```

This checks for Lima, Rosetta, rsync, Claude Code and a key in your SSH
agent, and prints the fix next to anything missing. Two rows are expected
to be flagged at this point: the Claude token and `dev-base`, which the next
two steps provide.

### 3. Load your SSH key (optional)

```bash
ssh-add -l || ssh-add ~/.ssh/id_ed25519
```

Skip this if you will not push from inside a VM. `git push` in a VM borrows
the key through the forwarded agent, so the agent on the Mac needs it
loaded; the alternative is to let `new` copy your `~/.ssh` private keys into
the VM when it asks (see [Everyday tasks](everyday.md)). Doctor's `SSH key`
row shows which of the two you have.

### 4. Give lima-ai a Claude token (once)

```bash
lima-ai auth
```

This runs `claude setup-token`, which signs you in to your Claude account
and prints a long-lived token. Paste it at the prompt (input is hidden). It is stored in
`~/.config/lima-ai/oauth-token` with mode 600 and copied into each VM over
stdin, so it never shows up in a process list.

### 5. Build the base VM (once)

```bash
lima-ai base
```

This takes about 5–10 minutes. The first run also downloads the Ubuntu
26.04 image. When it finishes, `dev-base` is stopped and ready to clone.
Rebuild it later with `lima-ai base --rebuild`; existing workspace VMs are not
affected.

### 6. Create a workspace VM

```bash
lima-ai new
```

`new` asks for what you leave out. With [fzf](https://github.com/junegunn/fzf)
installed (`brew install fzf`) you pick the project folder from a fuzzy list;
without it, you type the folder. Then it asks for a workspace name (a short
label for what this VM is for) and, when the project uses git, for the
branch, with the workspace name prefilled:

```
Project> preludian/myapp  (git)
Workspace name: feat-login
Git branch [feat-login]:
```

The same, with nothing to ask: `lima-ai new preludian/myapp feat-login`.
Pass `--branch NAME` to choose the branch or `--no-branch` to stay on the
host's branch.

In under a minute this clones `dev-base`, starts the clone, copies in your
Claude token, `~/.claude` config, git config and the project, and switches
to the branch. The VM then prints its connection card with a few tips about
the box, and `new` offers to open a shell:

```
+---------------------------------------------+
| LIMA-AI - Instance Details                  |
+---------------------------------------------+
| Project:    preludian/myapp                 |
| Workspace:  feat-login                      |
| FQDN:       lima-dev-myapp-feat-login.local |
| IP:         192.168.64.8                    |
| Created at: 2026-11-01T14:03:22Z            |
| Git branch: feat-login                      |
+---------------------------------------------+

* This is an Ubuntu 26.04 box. Install whatever you want; Claude may install things here too.
* Run `cc` for Claude Code with permissions skipped (claude --dangerously-skip-permissions).
* Installed here: docker, git, lazygit, tmux, rg, fzf, jq, node 24, npm, cargo, claude, rtk, docker-backup.
* rtk trims the command output Claude reads. See what it saved with `rtk gain`.
* Print this again with `lima-ai-info`.
Open it with: lima-ai shell preludian/myapp feat-login
Open a shell in it now? [Y/n]:
```

If the project folder has no git repository, `new` says so: no branch is
created, and `destroy` cannot check that VM for unsaved work.

### 7. Work inside it

```bash
lima-ai shell preludian/myapp feat-login
```

The shell greets you with the same card and tips, once per session, and you
land in the VM's working copy, `~/work/myapp`. From there:

```bash
docker compose up -d     # your app, on the VM's own address
cc                       # claude --dangerously-skip-permissions
```

If the app listens on port 8002, open
`http://lima-dev-myapp-feat-login.local:8002` in your Mac's browser. Inside
the VM, `lima-ai-info` prints the card and tips again, handy for agents that
need to tell you where the app runs. Ports published by `docker compose` listen on
every interface, so they are reachable. A server you start by hand must bind
`0.0.0.0` rather than `127.0.0.1` to be reachable from the Mac.

### 8. Start a second workspace in parallel

```bash
lima-ai new preludian/myapp feat-billing --branch feat/billing
lima-ai list
```

```
PROJECT          WORKSPACE     STATUS   BRANCH        FQDN
preludian/myapp  feat-billing  Running  feat/billing  lima-dev-myapp-feat-billing.local
preludian/myapp  feat-login    Running  feat-login    lima-dev-myapp-feat-login.local
```

Both apps can now run on the same port, each at its own address.

### 9. Ship the work

Inside the VM, commit and push as usual. Git uses your name, email and
aliases from the Mac.

```bash
git push -u origin feat-login
```

Then open a pull request, or fetch the branch into your host checkout.

### 10. Clean up

```bash
lima-ai destroy preludian/myapp feat-login
```

!!! note
    `destroy` looks for uncommitted changes and unpushed commits in the VM before
    deleting it. If it finds any, it lists them and asks a second time;
    `--yes` skips only the first question, and `--force` skips both.

See [Everyday tasks](everyday.md) for syncing, pausing and backing up VMs,
and the [Command reference](commands.md) for every flag.
