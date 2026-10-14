# Troubleshooting

Start with `lima-ai doctor`. It checks the platform, Rosetta, Lima,
rsync, Claude Code, your SSH agent, `config.toml`, the Claude token,
`dev-base` and docker-backup, then lists each problem with the command
that fixes it.

**`new` failed halfway.** The VM is kept, and the error names the step that
failed. Fix the cause, then run `lima-ai sync …` if the project copy failed,
or `lima-ai sync-claude …` for the token, Claude or git steps. To start
over, run `lima-ai rm … --force`.

**"dev-base is running".** Clones are made from a stopped base. Stop it with
`limactl stop dev-base`.

**A `.local` name does not resolve.** Check that the VM is running
(`lima-ai ls`), then ask macOS directly:
`dscacheutil -q host -a name lima-dev-myapp-feat-login.local`. The IP in the
`ls` output works as well.

**`git push` fails with "Permission denied (publickey)".** Load your key on
the Mac (`ssh-add -l` should list it), then open a new `lima-ai shell`.

**Compose warns "volume … was not created by Docker Compose" after a
restore.** This is harmless. Restored volumes don't carry compose's labels,
and compose uses the restored data anyway.

**Lima warns "provisioning scripts should not reference the LIMA_CIDATA
variables".** This is harmless; the base provisioning uses that variable to
add you to the `docker` group.

**`chronyc` in a VM does not answer.** Run it with `sudo`. Its network
command port is closed so that nothing from a VM is forwarded to your Mac.
