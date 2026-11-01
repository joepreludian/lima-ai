# Configuration

Everything works without a config file. To change defaults, create
`~/.config/lima-ai/config.toml`. Unknown keys are an error, so typos don't
go unnoticed.

```toml
developer_dir = "~/Developer"                 # where <project> paths start
backups_dir   = "~/Developer/backups/docker"  # mounted read-write in every VM

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

[sync]
extra_excludes = ["*.sqlite3"]                # added to the project rsync excludes
ssh_keys = false                              # copy ~/.ssh private keys into VMs; unset = ask once and save the answer
```

Mounts, VM defaults and tool versions are fixed when `dev-base` is built.
After changing `developer_dir`, `backups_dir`, `[vm]` or `[versions]`, run
`lima-ai base --rebuild`; VMs you already created keep their old settings.

Files lima-ai keeps on your Mac:

| Path | Contents |
|---|---|
| `~/.config/lima-ai/oauth-token` | Claude token (mode 600) |
| `~/.config/lima-ai/config.toml` | optional settings |
| `~/.local/state/lima-ai/base/` | the rendered `dev-base` template and its provision scripts |
| `~/.local/state/lima-ai/instances/` | which project and workspace each VM belongs to, and when it was created, for `list` |
| `~/Developer/backups/docker/` | Docker backups |

`XDG_CONFIG_HOME` and `XDG_STATE_HOME` are respected when set.
