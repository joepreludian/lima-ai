# Command reference

| Command | What it does |
|---|---|
| `doctor` | Check that this machine has the tools and setup lima-ai needs; exits 1 if something required is missing |
| `auth [--from-stdin]` | Run `claude setup-token` and store the token (mode 600) |
| `base [--rebuild]` | Build, check, seal and stop `dev-base` |
| `template` | Print the rendered `dev-base` Lima template |
| `new [<project>] [<workspace>] [--branch NAME \| --no-branch] [--restore BACKUP] [--cpus N] [--memory 16GiB] [--disk 100GiB]` | Create a workspace VM; asks for the project (fzf when installed), the workspace and the branch when they are not given |
| `shell [<project> <workspace>]` | Open a shell in the VM's working copy, with your SSH agent forwarded; with no arguments, picks the VM for you |
| `list` (alias `ls`) | List workspace VMs with project, workspace, status, branch and FQDN |
| `sync <project> <workspace>` | Copy the host project into the VM again |
| `sync-claude <project> <workspace>` | Copy the Claude token, Claude config, git config and (if enabled) SSH keys again |
| `start <project> <workspace>` / `stop <project> <workspace>` | Start or stop a workspace VM |
| `destroy <project> <workspace> [--yes] [--force]` | Delete a workspace VM after checking for unsaved work |
| `backup <project> <workspace> [--full] [--no-images] [--no-external] [--compose-file FILE]...` | Back up the project's Docker data to the backups folder |
| `restore <project> <workspace> <backup> [--overwrite] [--full] [--compose-file FILE]...` | Restore a backup into the VM |

Add `-v` before a command (`lima-ai -v new …`) to print every command
lima-ai runs.

`lima-ai shell` on its own opens the only running workspace VM. With several
running it shows a menu (arrow keys or `j`/`k`, Enter to pick, Ctrl-C to
cancel) where stopped VMs are dimmed and cannot be picked. With none running
it says so and lists the stopped ones. When stdin is not a terminal it prints
the `list` table and the command to type instead.

## Inside a VM

`new` and `sync-claude` install one helper into the VM's `~/.local/bin`:

| Command | What it does |
|---|---|
| `lima-ai-info` | Print the VM's connection card: project, workspace, FQDN, IP, creation time and current git branch |

`new` runs it for you when the VM is ready. It reads `~/.config/lima-ai/instance`,
which `new` writes; on a VM made by an older lima-ai, `sync-claude` creates
that file with an unknown creation time.

They also install lima-ai's bash prompt, `~/.config/lima-ai/prompt.sh`,
sourced from the end of `~/.bashrc`. It shows, in color, the VM's mDNS name,
the workspace, the current folder and the git branch of that folder (or the
commit when HEAD is detached):

```
l-ai lima-dev-myapp-feat-login.local feat-login ~/work/myapp (feat-login)$
```

Remove the `# lima-ai prompt` lines from `~/.bashrc` to get the stock prompt
back.

## Names

| | Example for `preludian/myapp` + `feat_login` |
|---|---|
| Workspace name | `feat-login` (lowercased; other characters become `-`) |
| VM (Lima instance) | `dev-myapp-feat-login` |
| mDNS name | `lima-dev-myapp-feat-login.local` |
| Working copy in the VM | `~/work/myapp` |

Only the last folder of the project path names the VM. `a/myapp` and
`b/myapp` therefore cannot have a workspace with the same name at the same
time; `new` refuses rather than overwrite an existing VM. Hostnames longer
than 63 characters are rejected, so pick a shorter workspace name.
