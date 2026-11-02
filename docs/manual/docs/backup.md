# Backup and restore

A workspace VM is disposable, but the Docker data inside it often is not: a
database you seeded by hand, an upload folder, an image that takes twenty
minutes to build. `lima-ai backup` saves that data to a folder on your Mac, and
`lima-ai restore` loads it into any VM, including a brand-new one. This page
explains what is saved, where it goes, how the two commands decide what to
touch, and what happens when something goes wrong.

The work is done by [docker-backup](https://docker-backup.readthedocs.io),
which is installed in every VM. lima-ai decides which compose files to hand it,
stops and starts your compose stack around it, and keeps every backup inside
one folder that the host and the VMs share. The command reference lists the
flags; this page explains the behaviour behind them.

## Where backups live

`backups_dir` (default `~/Developer/backups/docker`, see
[Configuration](configuration.md)) is mounted **read-write** into every VM at
`/backups/docker`. It is the only place a VM can write on your Mac. Backups are
written straight into that mount, so there is no copy step: when `backup`
finishes, the folder is already on your disk, and anything you put there from
the Mac is already visible to every VM.

Each backup is a folder named after the VM it came from and the time it was
taken:

```text
~/Developer/backups/docker/
├── myapp-feat-login-20260926T141500Z/        # one project
└── myapp-feat-login-full-20260926T153000Z/   # the whole daemon (--full)
```

The first part is the project's short name (the last segment of the project
path, so `preludian/myapp` gives `myapp`), then the workspace, then `full`
when the whole daemon was backed up, then a UTC timestamp. Inside, the layout
is docker-backup's own:

```text
myapp-feat-login-20260926T141500Z/
├── manifest.json       # what is in the backup, with hashes
├── volumes/<name>.tar  # one tar per named volume
└── images/<ref>.tar    # one tar per locally built image
```

Because it is a plain folder, you can copy it, rsync it to another machine,
or restore from it with `docker-backup` directly, without lima-ai.

!!! note "The folder is the unit"

    `restore` accepts any path **inside** `backups_dir`, absolute or relative
    to it, but refuses anything outside it and the folder itself. Keep each
    backup in its own subfolder; docker-backup refuses to write into a folder
    that already holds a `manifest.json`.

## What a backup contains

By default `backup` saves one compose project: the volumes it uses and the
images it built. Everything is decided by rendering the project with
`docker compose config`, so overrides, `.env` substitution, profiles and
`extends` are all honoured.

| In the compose project | Backed up? |
| --- | --- |
| A named volume (`pgdata:/var/lib/postgresql/data`) | yes, under the name compose gives it, e.g. `myapp_pgdata` |
| An external volume (`external: true`) | yes, marked external, unless `--no-external` |
| The image of a service with `build:` | yes, when the daemon recorded it as built locally; skipped with `--no-images` |
| The image of a service with only `image:` | no: it can be pulled again |
| A bind mount (`./data:/data`) | no: those files are already on your Mac, or in the VM's working copy |
| An anonymous volume (`- /data`) | no |
| Containers | no: `docker compose up` recreates them |

A volume or image the project declares but the VM does not have yet, say a
service that was never started, is listed as `skipped (not found)` and is not
an error. If *nothing* the project declares exists in the VM, docker-backup
stops before writing anything.

With `--full`, the scope is the whole Docker daemon in the VM: every named
volume and every locally built image, whichever project they belong to. Use it
when a workspace runs several compose projects, or when the data you want is
not described by any compose file.

## Finding the compose files

lima-ai looks at the top level of the VM's working copy and picks the files
plain `docker compose` would load there:

1. If `.env` sets `COMPOSE_FILE`, that list is used as is, split on
   `COMPOSE_PATH_SEPARATOR` (default `:`).
2. Otherwise the first of `compose.yaml`, `compose.yml`,
   `docker-compose.yml`, `docker-compose.yaml` that exists, plus the first
   matching `compose.override.*` or `docker-compose.override.*` when there is
   one.

`--compose-file FILE` (repeatable, paths relative to the project root)
replaces detection entirely. Use it for a stack that lives in a subfolder, or
to layer a file compose would not pick up on its own, such as
`docker-compose.prod.yml`. The files are passed to docker-backup in the order
given, like `docker compose -f`.

For a project backup, finding no compose file is an error that points you to
`--compose-file` or `--full`. For `--full`, and for `restore`, the compose
files only decide whether there is a stack to stop and start.

## `lima-ai backup` step by step

```bash
lima-ai backup preludian/myapp feat-login
lima-ai backup preludian/myapp feat-login --no-images --compose-file compose.yml --compose-file compose.prod.yml
lima-ai backup preludian/myapp feat-login --full
```

1. **The VM must be running.** `backup` does not start it for you.
2. **Compose files are detected** as above, or taken from `--compose-file`.
3. **The stack is stopped** with `docker compose stop`, because volumes are
   read live: a database writing while its volume is tarred can produce a
   backup that verifies and still will not start. Without a compose file
   (only possible with `--full`) nothing is stopped, and lima-ai says so.
4. **docker-backup runs** interactively, so you see its progress and its
   per-item table. Its output lands in a new folder under `/backups/docker`.
5. **The stack is started again** with `docker compose start`, even when the
   backup failed. Containers come back exactly as they were; nothing is
   recreated.
6. **`docker-backup info`** prints the manifest and verifies the files, so a
   backup that is unreadable is caught now rather than at restore time.
7. **The host commands are printed.** See the next section.

Flags:

| Flag | Effect |
| --- | --- |
| `--no-images` | Volumes only. Images are rebuilt from the project anyway; skip them when the build is quick and the backup should stay small. |
| `--no-external` | Leave out volumes the compose file marks `external: true`. Those are usually shared between projects, so a restore on the host could touch another project's data. |
| `--compose-file FILE` | Use these compose files instead of detecting them. Repeatable. |
| `--full` | Back up the whole daemon. Cannot be combined with `--no-external` or `--compose-file`. |

With `--full`, the project's own stack is still stopped when there is one, but
other projects' containers keep running and their volumes are read live.

### The host commands

`backup` ends by printing the commands that would load the backup into your
Mac's Colima, for example:

```text
Backup written to ~/Developer/backups/docker/myapp-feat-login-20260926T141500Z
To bring it into the host's Colima:
  cd ~/Developer/preludian/myapp
  docker compose stop
  docker-backup info ~/Developer/backups/docker/myapp-feat-login-20260926T141500Z
  docker-backup restore --from-docker-compose compose.yaml ~/Developer/backups/docker/myapp-feat-login-20260926T141500Z              # new volumes only
  docker-backup restore --from-docker-compose compose.yaml ~/Developer/backups/docker/myapp-feat-login-20260926T141500Z --overwrite  # replaces this project's existing volumes
  docker compose up -d
```

lima-ai **never runs these**. The host's Docker is yours, docker-backup on the
Mac is optional, and overwriting a volume there is not something a VM tool
should do on its own. Two details worth knowing:

- The compose files in those commands are detected again from the **host's**
  checkout, not copied from the VM, because the two can differ. When you
  passed `--compose-file`, the same files are used on both sides.
- A note follows when `--overwrite` on the host could reach beyond the
  project: a full backup replaces every volume in its manifest that exists on
  the host, and a project backup taken without `--no-external` also replaces
  the project's external volumes.

## `lima-ai restore` step by step

```bash
lima-ai restore preludian/myapp feat-billing myapp-feat-login-20260926T141500Z
lima-ai restore preludian/myapp feat-billing myapp-feat-login-20260926T141500Z --overwrite
lima-ai restore preludian/myapp feat-billing myapp-feat-login-full-20260926T153000Z --full
```

1. **The path is checked** before anything else: it must exist and be inside
   `backups_dir`.
2. **The VM must be running.**
3. **The manifest is read.** A single-volume archive (made with
   `docker-backup backup-volume`) is refused, with the `restore-volume`
   command to run by hand from `lima-ai shell`.
4. **`docker-backup info`** shows what is in the backup and verifies it.
5. **With `--overwrite`, lima-ai asks first.** Every volume the project uses
   that already exists in the VM, external ones included, will be emptied and
   refilled. This is lima-ai's own question; docker-backup asks its own later.
6. **The stack is stopped** when the working copy has a compose file.
7. **docker-backup restores**, interactively and without `--yes`: it shows a
   preview of what it will create, overwrite or skip, and asks you to confirm.
   That prompt is the real confirmation for a plain restore.
8. **The stack is started** with `docker compose up -d` when everything
   restored, so new volumes are picked up.

### Volume names follow the restoring project

Compose names volumes after the project, and the project is named after its
folder. The VM's working copy is always at the same path for a given project,
but a backup taken on the Mac, or from a project checked out under another
name, carries different volume names. A project backup records each volume's
key in the compose file (`pgdata`), and the restore looks that key up in the
project as it is now, so `shop_pgdata` in the backup fills `myapp_pgdata` in
the VM. Built images get the project's current tags the same way. External
volumes and volumes with an explicit `name:` keep their names, since the
project name does not affect them. The preview lists every rename before you
confirm, and the project's volumes that nothing in the backup maps to.

Restored volumes do not carry compose's labels. The first `docker compose up`
warns that a volume "was not created by Docker Compose". That is harmless and
lima-ai says so; compose mounts the restored data anyway.

### Existing volumes

By default a volume that already exists in the VM is **skipped**, whatever it
contains. That makes a plain restore safe to repeat and right for a fresh VM.
To replace data that is already there, pass `--overwrite`: the volume is
emptied and refilled from the backup. There is no merge.

### `--full` and backups without a compose file

`--full` restores everything in the backup under the names recorded in it,
with no mapping to the current project. It cannot take `--compose-file`. Use
it for a backup made with `backup --full`, or when the VM's working copy has
no compose file: in that case lima-ai has nothing to map against and restores
the whole backup under recorded names even without `--full`.

A full backup can also be restored **as a project**: run `restore` without
`--full` and only the entries whose volume name or image tag the project uses
now are loaded. A full backup records no compose keys, so there is nothing to
rename by: a project checked out under another name finds nothing in it.

### What happens when it fails

lima-ai reads docker-backup's exit code and leaves the VM in a known state:

| docker-backup exit | What it means | What lima-ai does |
| --- | --- | --- |
| `0` | everything restored | starts the stack with `docker compose up -d` |
| `2` | nothing was changed: you declined at the prompt, the backup holds nothing for this project, or a compose file was rejected | starts the stack again with `docker compose start` and reports the reason |
| `3` | docker or the compose plugin is unavailable in the VM | same as `2` |
| `1` or other | an item failed part-way | **leaves the stack stopped** and tells you |

After a partial failure a volume may have been created or emptied before the
failure and be only partly filled. Fix the cause, then run the same `restore`
again with `--overwrite` to refill it, and start the stack yourself if you
decide not to.

## Restoring into a new VM

```bash
lima-ai new preludian/myapp feat-review --restore myapp-feat-login-20260926T141500Z
```

`--restore` is checked up front, so a wrong path fails before any VM is
cloned. The restore runs as the last step of `new`, after the project is
synced and the branch is switched, as a project restore without
`--overwrite`. In a fresh VM every volume is new, so everything in the backup
that belongs to the project is loaded. If the restore fails, the VM is kept
and the error says how to retry or discard it, like any other `new` failure.

## Recipes

**Fork a workspace with its data.** Back up the VM you have, then create the
new one from the backup:

```bash
lima-ai backup preludian/myapp feat-login
lima-ai new preludian/myapp feat-login-2 --restore myapp-feat-login-20260926T141500Z
```

**Bring VM data to your Mac.** Run `backup`, then the printed commands. They
need docker-backup on the host (`brew install joepreludian/tap/docker-backup`)
and a running Colima.

**Seed a VM from your Mac's Docker.** The mount works both ways. Take the
backup on the host, straight into `backups_dir`, then restore it in the VM:

```bash
cd ~/Developer/preludian/myapp
docker compose stop
docker-backup backup --from-docker-compose compose.yaml ~/Developer/backups/docker/myapp-host-$(date -u +%Y%m%dT%H%M%SZ)
docker compose start
lima-ai restore preludian/myapp feat-login myapp-host-20260926T160000Z
```

**Refresh a long-lived workspace from a newer backup.** `restore --overwrite`,
after stopping anything that must not lose its state.

**Keep only the data.** `backup --no-images` when the images are cheap to
rebuild; `restore` then rebuilds them on `docker compose up -d` as usual.

## What lima-ai does not do

- **List, prune or rotate backups.** `backups_dir` is a plain folder; `ls` it
  and delete what you no longer need.
- **Back up on `destroy`.** `destroy` checks the working copy for
  uncommitted and unpushed git work, not for Docker data. Run `backup` first
  when the volumes matter.
- **Schedule backups.** Each backup is a deliberate command.
- **Check that a backup belongs to the project.** The name tells you where it
  came from; docker-backup's preview tells you what will be loaded. Read both
  before confirming.
- **Restore single-volume archives.** Use `docker-backup restore-volume` from
  `lima-ai shell`.
- **Touch the host's Docker.** Commands are printed, never run.

## Troubleshooting

**"no compose file found in the VM's ~/…"**: the working copy has no compose
file at its top level. Pass `--compose-file` with the real path, or `--full`.

**"none of compose project … volumes or images exist on this docker daemon"**:
the stack was never started in this VM, so there is nothing to save. Run
`docker compose up` in the VM once, or check the compose files.

**"docker-backup exited 2, so nothing was changed"**: you said no at the
prompt, or the backup holds nothing for this project (for example a project
backup from a different compose project). Run `docker-backup info` on it from
`lima-ai shell` to see what it holds, and consider `--full`.

**Warning "volume … was not created by Docker Compose" after a restore**:
harmless, see above.

**`doctor` warns about docker-backup**: that is the host copy, needed only to
restore into Colima. VMs carry their own, pinned in `[versions]`.
