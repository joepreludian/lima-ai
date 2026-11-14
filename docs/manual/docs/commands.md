# Command reference

| Command | What it does |
|---|---|
| `doctor` | Check that this machine has the tools and setup lima-ai needs; exits 1 if something required is missing |
| `auth [--from-stdin]` | Run `claude setup-token` and store the token (mode 600) |
| `base [--rebuild] [--use-hook PATH \| --init-hook PATH]` | Build, check, seal and stop `dev-base`; `--use-hook` runs your script in it after provisioning and remembers it, `--init-hook` writes a commented starter and exits (see [The base image](base-image.md)) |
| `config [--edit]` | Print the effective settings as TOML; `--edit` opens `~/.config/lima-ai/config.toml` in `$VISUAL`/`$EDITOR`, creating it with every setting commented out |
| `template` | Print the rendered `dev-base` Lima template |
| `new [<project>] [<workspace>] [--branch NAME \| --no-branch] [--cpus N] [--memory 16GiB] [--disk 100GiB] [--aws \| --no-aws] [--hooks \| --no-hooks]` | Create a workspace VM; asks for the project (fzf when installed), the workspace and the branch when they are not given, whether to copy `~/.aws`, and (once) which host hooks to copy |
| `shell [<project> <workspace>]` | Open a shell in the VM's working copy, with your SSH agent forwarded; with no arguments, picks the VM for you |
| `list` (alias `ls`) | List workspace VMs with project, workspace, status, branch and FQDN |
| `sync [<project> <workspace>]` | Copy the host project into the VM again |
| `sync-claude [<project> <workspace>] [--aws \| --no-aws] [--hooks \| --no-hooks]` | Copy the Claude token, Claude config, the host hooks you chose, git config, (if enabled) SSH keys and (if confirmed) AWS config again; `--hooks` shows the hook checklist again, `--no-hooks` copies none this time |
| `start [<project> <workspace>]` / `stop [<project> <workspace>]` | Start or stop a workspace VM |
| `destroy [<project> <workspace>] [--yes] [--force]` | Delete workspace VMs after checking for unsaved work; with no arguments, pick them from a checklist |

`sync`, `sync-claude`, `start` and `stop` pick the VM from a menu when you
give neither `<project>` nor `<workspace>`: the running VMs, or for `start`
the stopped ones. Outside a terminal they use the only candidate and say
which, or list them and stop when there are several.

Add `-v` before a command (`lima-ai -v new …`) to print every command
lima-ai runs.

`lima-ai shell` on its own opens the only running workspace VM. With several
running it shows a menu (arrow keys or `j`/`k`, Enter to pick, Ctrl-C to
cancel) where stopped VMs are dimmed and cannot be picked. With none running
it says so and lists the stopped ones. When stdin is not a terminal it prints
the `list` table and the command to type instead.

`lima-ai destroy` on its own lists every workspace VM, running and stopped,
with a checkbox each (space to tick, `a` for all, `i` to invert, Enter to
confirm, Ctrl-C to cancel). It then checks the ticked running VMs for unsaved
work, shows what it will delete, asks once, and deletes them. `--force` skips
that question; `--yes` skips it unless a ticked VM holds unsaved work. When
stdin is not a terminal it prints the `list` table and asks for the names
instead.

## Inside a VM

`new` and `sync-claude` install two helpers into the VM's `~/.local/bin`:

| Command | What it does |
|---|---|
| `lima-ai-info` | Print the VM's connection card (project, workspace, FQDN, IP, creation time and current git branch), then tips: the Ubuntu release, the `cc` alias, which of the base image's tools are installed, and `rtk gain` |
| `lima-ai-claude-setup` | Mark Claude's onboarding as done in `~/.claude.json` and wire rtk into `~/.claude` (`rtk init -g --auto-patch`); both commands run it after copying the Claude config |

`new` runs it for you when the VM is ready. It reads `~/.config/lima-ai/instance`,
which `new` writes; on a VM made by an older lima-ai, `sync-claude` creates
that file with an unknown creation time.

They also install lima-ai's bash prompt, `~/.config/lima-ai/prompt.sh`,
sourced from the end of `~/.bashrc`. It runs `lima-ai-info` once per shell
session (shells started from that one, such as tmux panes, inherit
`LIMA_AI_GREETED` and stay quiet), then shows, in color, the VM's mDNS name,
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
