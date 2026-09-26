#!/bin/bash
# Seals dev-base so that every clone boots with its own machine-id (so its own
# DHCP lease and mDNS identity) and its own SSH host keys. Runs as root.
set -euo pipefail

docker system prune -af
apt-get clean

# Host keys are removed below; regenerate them before sshd's config check.
mkdir -p /etc/systemd/system/ssh.service.d
cat > /etc/systemd/system/ssh.service.d/lima-ai-host-keys.conf <<'UNIT'
[Service]
ExecStartPre=
ExecStartPre=/usr/bin/ssh-keygen -A
ExecStartPre=/usr/sbin/sshd -t
UNIT
systemctl daemon-reload
rm -f /etc/ssh/ssh_host_*

truncate -s 0 /etc/machine-id
rm -f /var/lib/dbus/machine-id
