# Command reference

| Command | What it does |
|---|---|
| `doctor` | Check that this machine has the tools and setup lima-ai needs; exits 1 if something required is missing |
| `auth [--from-stdin]` | Run `claude setup-token` and store the token (mode 600) |
| `base [--rebuild]` | Build, check, seal and stop `dev-base` |
| `template` | Print the rendered `dev-base` Lima template |
| `new <project> <feat> [--branch NAME] [--restore BACKUP] [--cpus N] [--memory 16GiB] [--disk 100GiB]` | Create a feature VM |
| `shell <project> <feat>` | Open a shell in the VM's working copy, with your SSH agent forwarded |
| `ls [--port N]` | List feature VMs with status, mDNS name, IP and URL |
| `sync <project> <feat>` | Copy the host project into the VM again |
| `sync-claude <project> <feat>` | Copy the Claude token, Claude config, git config and (if enabled) SSH keys again |
| `start <project> <feat>` / `stop <project> <feat>` | Start or stop a feature VM |
| `rm <project> <feat> [--yes] [--force]` | Delete a feature VM after checking for unsaved work |
| `backup <project> <feat> [--full] [--no-images] [--no-external] [--compose-file FILE]...` | Back up the project's Docker data to the backups folder |
| `restore <project> <feat> <backup> [--overwrite] [--full] [--compose-file FILE]...` | Restore a backup into the VM |

Add `-v` before a command (`lima-ai -v new …`) to print every command
lima-ai runs.

## Inside a VM

`new` and `sync-claude` install one helper into the VM's `~/.local/bin`:

| Command | What it does |
|---|---|
| `lima-ai-info` | Print this VM's FQDN, e.g. `lima-dev-myapp-feat-login.local` |

## Names

| | Example for `preludian/myapp` + `feat_login` |
|---|---|
| Feature name | `feat-login` (lowercased; other characters become `-`) |
| VM (Lima instance) | `dev-myapp-feat-login` |
| mDNS name | `lima-dev-myapp-feat-login.local` |
| Working copy in the VM | `~/work/myapp` |

Only the last folder of the project path names the VM. `a/myapp` and
`b/myapp` therefore cannot have a feature with the same name at the same
time; `new` refuses rather than overwrite an existing VM. Hostnames longer
than 63 characters are rejected, so pick a shorter feature name.
