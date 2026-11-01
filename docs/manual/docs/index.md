# Introduction

Run several Claude Code agents in parallel on a Mac, each in its own
disposable Linux VM, each working on one workspace of your project: a
branch, an experiment, a review.

```
lima-ai new preludian/myapp feat-login     →  lima-dev-myapp-feat-login.local
lima-ai new preludian/myapp feat-billing   →  lima-dev-myapp-feat-billing.local
```

Every VM gets its own copy of the project, its own Docker daemon and its own
network address. The same `docker compose` app can run on the same port in
every VM at once, and you open each one by name from your Mac's browser.
Inside a VM the agent has full control: root, Docker, and `claude
--dangerously-skip-permissions` with no permission prompts. It still cannot
write to your Mac's files, except for one backup folder.

## How it works

### A golden base, cloned per workspace

`lima-ai base` builds one Ubuntu VM, `dev-base`, with Docker, Node, Rust,
Claude Code, rtk and docker-backup. It checks the toolchain, then seals the
VM: the machine-id and SSH host keys are wiped, so every clone boots with its
own identity. `lima-ai new` clones that base, which takes seconds instead of
a fresh install, and fills the clone:

```mermaid
sequenceDiagram
    actor You
    participant CLI as lima-ai (your Mac)
    participant Lima as limactl
    participant VM as dev-myapp-feat-login

    You->>CLI: lima-ai new preludian/myapp feat-login
    CLI->>Lima: clone dev-base, then start the clone
    Lima->>VM: boot with a new machine-id, SSH host keys and IP
    CLI->>VM: Claude token (over stdin, never in argv)
    CLI->>VM: rsync the ~/.claude subset and git config
    CLI->>VM: lima-ai-info and the instance file (project, workspace, creation time)
    CLI->>VM: rsync the project into ~/work/myapp
    opt branch or --restore
        CLI->>VM: git switch, docker-backup restore
    end
    CLI-->>You: the VM's connection card, then an offer to open a shell
```

### Every VM has its own address

Each VM sits on a `vzNAT` network with its own IP and publishes
`lima-<instance>.local` over mDNS (avahi), which your Mac resolves with no
setup. Lima's usual forwarding of guest ports to your Mac's `localhost` is
switched off entirely, so every VM can serve on the same port (say, 8002)
without a clash:

```mermaid
flowchart LR
    browser["Browser<br/>on your Mac"]
    subgraph vznat["vzNAT network"]
        login["dev-myapp-feat-login<br/>192.168.64.8<br/>app on :8002"]
        billing["dev-myapp-feat-billing<br/>192.168.64.9<br/>app on :8002"]
    end
    localhost["Your Mac's<br/>localhost"]

    browser -- "lima-dev-myapp-feat-login.local:8002" --> login
    browser -- "lima-dev-myapp-feat-billing.local:8002" --> billing
    login -. "not forwarded" .-x localhost
    billing -. "not forwarded" .-x localhost
```

### Copies, not shared folders

The project, your Claude config and your git config are copied into the VM
with rsync, so an agent works on its own files. After that, the working copy
is an ordinary git checkout that pushes to and pulls from your project's own
remotes. Two host folders are mounted as well: `~/Developer` read-only, and
the Docker backups folder read-write.

```mermaid
flowchart LR
    subgraph mac["Your Mac"]
        project["~/Developer/preludian/myapp"]
        claude["~/.claude"]
        gitconfig["~/.gitconfig<br/>~/.ssh/known_hosts"]
        token["~/.config/lima-ai/oauth-token"]
        developer["~/Developer"]
        backups["~/Developer/backups/docker"]
    end
    subgraph vm["dev-myapp-feat-login"]
        work["~/work/myapp<br/>(git checkout)"]
        vclaude["~/.claude"]
        vgit["~/.gitconfig<br/>~/.ssh/known_hosts"]
        env["~/.config/lima-ai/env"]
        ro["/Users/you/Developer<br/>(read-only)"]
        rw["/backups/docker<br/>(read-write)"]
    end
    remote[("Git remote")]

    project -- "rsync" --> work
    claude -- "rsync: subset, host paths rewritten" --> vclaude
    gitconfig -- "rsync: Mac-only settings removed" --> vgit
    token -- "stdin" --> env
    developer -. "mount" .-> ro
    backups <-. "mount" .-> rw
    work <-- "git push / pull" --> remote
```

### What an agent in a VM can and cannot do

| | |
|---|---|
| Root, `sudo`, Docker, install anything | yes, inside its VM |
| Read your projects | yes: `~/Developer` is mounted **read-only** at the same path |
| Write to your Mac's files | only `~/Developer/backups/docker` (mounted at `/backups/docker`) |
| Expose ports on your Mac's `localhost` | no: no VM port is forwarded to your Mac |
| Reach services on your Mac | yes: `host.lima.internal` reaches your Mac's `localhost`, like any Lima VM |
| Use your SSH key | yes, through the forwarded `ssh-agent` while an SSH connection to the VM is open; the key file never enters the VM |
| Use Claude | with a long-lived token from `claude setup-token` (your Max subscription) |

!!! warning
    Anything the agent pushes to a git remote leaves the VM, so review
    branches before you merge them. Services listening on your Mac's
    `localhost` (a local database, say) are reachable from every VM, so
    don't leave anything there that an agent shouldn't touch.

## Next steps

- [Installation](install.md): requirements and how to install lima-ai.
- [Quickstart](quickstart.md): run two workspaces of one project side by side.
