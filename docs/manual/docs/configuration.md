# Configuration

Everything works without a config file. To change defaults, create
`~/.config/lima-ai/config.toml`. Unknown keys are an error, so typos don't
go unnoticed.

```toml
developer_dir = "~/Developer"                 # where <project> paths start
backups_dir   = "~/Developer/backups/docker"  # mounted read-write at /backups in every VM

[vm]                                          # dev-base defaults; new --cpus/--memory/--disk override per VM
cpus   = 4
memory = "8GiB"
disk   = "60GiB"
ubuntu_release = "26.04"

[versions]                                    # pinned tools installed into dev-base
node_major = 24
rtk        = "0.49.0"
rtk_sha256 = "c8ea4b6560841e73157c134fd4a3293914c6ede42e786ee985cf491fde691ba7"
docker_backup        = "0.4.0"
docker_backup_sha256 = "9c7bdf7c25d4f8c19253a3ffd73bfd34e2d8d4f6e1cd7736b27feffbee8a22d8"
aws_cli           = "2.39.6"
aws_cli_sha256    = "5763332bdcb432c19ee122545856fd350c3bb306753212deedcfccc76f4d20c3"
ssm_plugin        = "1.2.896.0"
ssm_plugin_sha256 = "914eeca87b18b55356c58be197080f73742b3ca60d3823f0a45670dc9056aa9c"

[sync]
extra_excludes = ["*.sqlite3"]                # added to the project rsync excludes
ssh_keys = false                              # copy ~/.ssh private keys into VMs; unset = ask once and save the answer
hooks = ["~/.claude/hooks/check.sh"]          # host hook commands copied into VMs; unset = ask once and save the answer
hooks_skipped = []                            # host hook commands seen and declined

[base]
hook = "~/lima/custom.sh"                     # a script lima-ai base runs as root in dev-base after its own provisioning

[new]
post_create = [                               # commands lima-ai new runs on the Mac once the VM is ready
  'limactl copy ~/.claude-display/hook.env "$LIMA_AI_VM":.claude-display/hook.env',
]
```

Mounts, VM defaults and tool versions are fixed when `dev-base` is built.
After changing `developer_dir`, `backups_dir`, `[vm]` or `[versions]`, run
`lima-ai base --rebuild`; VMs you already created keep their old settings.
The `hook` under `[base]` is your own additions to the image; `lima-ai base
--use-hook PATH` sets it. [The base image](base-image.md) explains how it runs.

`hooks` and `hooks_skipped` are written by the hook checklist that `new` and
`sync-claude` show; each entry is a hook command exactly as it appears in
`~/.claude/settings.json`. [Everyday tasks](everyday.md) explains what is
offered and what is copied.

`post_create` is for what your VMs need that lima-ai does not know about,
such as a settings file one of your hook scripts reads. `lima-ai new` runs
each command on your Mac through `bash -c`, in the order listed, after the
VM has its token, Claude config, kept hooks and project, and before it
prints the connection card. Every command gets these variables, so one line
works for every VM:

| Variable | Value |
|---|---|
| `LIMA_AI_VM` | the Lima instance name, as `limactl` wants it (`dev-myapp-feat-a`) |
| `LIMA_AI_PROJECT` | the project, as you pass it to `new` (`preludian/myapp`) |
| `LIMA_AI_WORKSPACE` | the workspace (`feat-a`) |
| `LIMA_AI_FQDN` | the VM's name on your network (`lima-dev-myapp-feat-a.local`) |

To run something inside the VM, call `limactl shell "$LIMA_AI_VM" ...`
yourself. When a command fails, `new` stops there and shows the command and
its error; the VM is ready and kept, and the commands after it are not run.
Only `new` runs them: `sync`, `sync-claude` and `start` do not.

`lima-ai config` prints the settings in effect, defaults included, headed by
a comment naming the file. `lima-ai config --edit` opens that file in
`$VISUAL` or `$EDITOR`; when there is none yet it creates one first with
every setting present but commented out at its default, so you uncomment
what you change and upgrades keep moving the defaults you did not touch.
After the editor closes the file is checked, and a mistake is reported the
way any config error is.

Files lima-ai keeps on your Mac:

| Path | Contents |
|---|---|
| `~/.config/lima-ai/oauth-token` | Claude token (mode 600) |
| `~/.config/lima-ai/config.toml` | optional settings |
| `~/.local/state/lima-ai/base/` | the rendered `dev-base` template and its provision scripts |
| `~/.local/state/lima-ai/instances/` | which project and workspace each VM belongs to, and when it was created, for `list` |
| `~/Developer/backups/docker/` | Docker backups |

`XDG_CONFIG_HOME` and `XDG_STATE_HOME` are respected when set.
