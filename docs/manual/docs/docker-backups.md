# Docker backups

A workspace VM is disposable, but the Docker data inside it often is not: a
database you seeded by hand, an upload folder, an image that takes twenty
minutes to build. Every VM comes with
[docker-backup](https://docker-backup.readthedocs.io) installed and with one
folder that it shares with your Mac. That is all lima-ai does about backups:
it provides the tool and the folder, and you run the tool. This page shows
the folder and a few commands to start from; docker-backup's own manual is
the reference for everything else.

## The shared folder

`backups_dir` (default `~/Developer/backups/docker`, see
[Configuration](configuration.md)) is mounted **read-write** into every VM
at `/backups`. It is the only place a VM can write on your Mac, and the mount
works both ways: a backup written in a VM is on your disk the moment it is
finished, and anything you put in the folder from the Mac is visible to every
VM. `lima-ai new` reminds you of both paths when it hands over a VM:

```text
Backups: /backups in the VM is ~/Developer/backups/docker on this Mac, read-write.
docker-backup is installed in the VM; see https://lima-ai.readthedocs.io/docker-backups/
```

The mount is fixed when `dev-base` is built, so after changing `backups_dir`
run `lima-ai base --rebuild`.

!!! warning "Upgrading from 0.11"

    VMs cloned from a `dev-base` built by lima-ai 0.11 or earlier mount the
    folder at `/backups/docker`. Run `lima-ai base --rebuild`; VMs created
    after that use `/backups`. The `backup` and `restore` commands of 0.11
    are gone; the commands below do the same work.

## From inside a VM

`lima-ai shell` opens in the project's working copy, where the compose file
is, so the commands below run as they are. Each backup is a folder: name it
after the project, the workspace and the time, and keep one backup per
folder, since docker-backup refuses to write into a folder that already holds
a `manifest.json`.

**Back up the compose project.** Stop the stack first: volumes are read
live, and a database writing while its volume is tarred can produce a backup
that verifies and still will not start.

```bash
lima-ai shell preludian/myapp feat-login
docker compose stop
docker-backup backup --from-docker-compose compose.yaml /backups/myapp-feat-login-$(date -u +%Y%m%dT%H%M%SZ)
docker compose start
```

This saves the named volumes the project uses and the images it built
locally; pulled images, bind mounts and containers are not included, because
`docker compose up` brings them back.

**Inspect and verify a backup.** `info` prints the manifest and checks the
files:

```bash
docker-backup info /backups/myapp-feat-login-20260926T141500Z
```

**Restore into another VM**, for example to fork a workspace together with
its data. docker-backup previews what it will create, overwrite or skip and
asks before it changes anything. Volumes that already exist are skipped
unless you add `--overwrite`, which empties and refills them.

```bash
lima-ai shell preludian/myapp feat-billing
docker compose stop
docker-backup restore --from-docker-compose compose.yaml /backups/myapp-feat-login-20260926T141500Z
docker compose up -d
```

The first `docker compose up` after a restore warns that a volume "was not
created by Docker Compose". That is harmless: restored volumes lack compose's
labels, and compose mounts the restored data anyway.

**The whole Docker daemon**, when a workspace runs several compose projects
or the data is not described by a compose file:

```bash
docker-backup backup /backups/myapp-full-$(date -u +%Y%m%dT%H%M%SZ)
docker-backup restore /backups/myapp-full-20260926T153000Z
```

## To and from your Mac

The folder is the same on both sides, so the same commands move data between
a VM and the Docker on your Mac. On the Mac they need docker-backup
(`brew install joepreludian/tap/docker-backup`) and a running Colima.

Bring a VM's backup into the Mac's Docker:

```bash
cd ~/Developer/preludian/myapp
docker compose stop
docker-backup restore --from-docker-compose compose.yaml ~/Developer/backups/docker/myapp-feat-login-20260926T141500Z
docker compose up -d
```

Seed a VM from the Mac's Docker: back up on the Mac straight into
`backups_dir`, then restore it from a shell in the VM as above.

```bash
cd ~/Developer/preludian/myapp
docker compose stop
docker-backup backup --from-docker-compose compose.yaml ~/Developer/backups/docker/myapp-host-$(date -u +%Y%m%dT%H%M%SZ)
docker compose start
```

## Good to know

- lima-ai never runs `docker compose` or `docker-backup` for you, in the VM
  or on the Mac, and it does not list, prune or schedule backups.
  `backups_dir` is a plain folder; `ls` it and delete what you no longer
  need.
- `lima-ai destroy` checks the working copy for uncommitted and unpushed git
  work, not for Docker data. Back up first when the volumes matter.
- `lima-ai doctor` warns when docker-backup is missing on the Mac. That copy
  is only for the Mac's own Docker; VMs carry their own, pinned under
  `[versions]` in the configuration.

Flags, exit codes, single-volume archives, how volumes are matched to a
project checked out under another name, and everything else docker-backup
does are in the [docker-backup manual](https://docker-backup.readthedocs.io).
