# Quickstart

This walk-through runs two features of the project at
`~/Developer/preludian/myapp` side by side. Substitute your own project path:
it is always a folder relative to `~/Developer`.

### 1. Load your SSH key (every login)

```bash
ssh-add -l || ssh-add --apple-use-keychain ~/.ssh/id_ed25519
```

VMs never receive your key. `git push` inside a VM borrows it through the
forwarded agent, so the agent needs the key loaded.

### 2. Give lima-ai a Claude token (once)

```bash
lima-ai auth
```

This runs `claude setup-token`, which signs you in to your Claude account
and prints a long-lived token. Paste it at the prompt (input is hidden). It is stored in
`~/.config/lima-ai/oauth-token` with mode 600 and copied into each VM over
stdin, so it never shows up in a process list.

### 3. Build the base VM (once)

```bash
lima-ai base
```

This takes about 5–10 minutes. The first run also downloads the Ubuntu
26.04 image. When it finishes, `dev-base` is stopped and ready to clone.
Rebuild it later with `lima-ai base --rebuild`; existing feature VMs are not
affected.

### 4. Create a feature VM

```bash
lima-ai new preludian/myapp feat-login --branch feat/login
```

In under a minute this clones `dev-base`, starts the clone, and copies in
your Claude token, `~/.claude` config, git config and the project. It then
creates the `feat/login` branch. It ends with a summary:

```
dev-myapp-feat-login is ready.
  mDNS   lima-dev-myapp-feat-login.local
  IP     192.168.64.8
  Shell  lima-ai shell preludian/myapp feat-login
```

### 5. Work inside it

```bash
lima-ai shell preludian/myapp feat-login
```

You land in the VM's working copy, `~/work/myapp`. From there:

```bash
docker compose up -d     # your app, on the VM's own address
cc                       # claude --dangerously-skip-permissions
```

If the app listens on port 8002, open
`http://lima-dev-myapp-feat-login.local:8002` in your Mac's browser. Inside
the VM, `lima-ai-info` prints that `.local` name, handy for scripts and for
agents that need to tell you where the app runs. Ports published by `docker
compose` listen on every interface, so they are reachable. A server you start by hand must bind `0.0.0.0` rather than
`127.0.0.1` to be reachable from the Mac.

### 6. Start a second feature in parallel

```bash
lima-ai new preludian/myapp feat-billing --branch feat/billing
lima-ai ls
```

```
PROJECT  FEAT          STATUS   MDNS                               IP            URL
myapp    feat-billing  Running  lima-dev-myapp-feat-billing.local  192.168.64.9  http://lima-dev-myapp-feat-billing.local:8002
myapp    feat-login    Running  lima-dev-myapp-feat-login.local    192.168.64.8  http://lima-dev-myapp-feat-login.local:8002
```

Both apps can now run on the same port, each at its own address.

### 7. Ship the work

Inside the VM, commit and push as usual. Git uses your name, email and
aliases from the Mac.

```bash
git push -u origin feat/login
```

Then open a pull request, or fetch the branch into your host checkout.

### 8. Clean up

```bash
lima-ai rm preludian/myapp feat-login
```

!!! note
    `rm` looks for uncommitted changes and unpushed commits in the VM before
    deleting it. If it finds any, it lists them and asks a second time;
    `--yes` skips only the first question, and `--force` skips both.

See [Everyday tasks](everyday.md) for syncing, pausing and backing up VMs,
and the [Command reference](commands.md) for every flag.
