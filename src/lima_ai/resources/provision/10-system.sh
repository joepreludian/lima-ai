#!/bin/bash
# Base packages, and avahi publishing <hostname>.local on the vzNAT interface.
set -euo pipefail
marker="/var/lib/lima-ai/10-system.done"
[ -e "$marker" ] && exit 0

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y build-essential pkg-config libssl-dev git rsync jq curl unzip \
  tmux ripgrep avahi-daemon libnss-mdns

# eth0 is Lima's user-mode network, identical in every VM; only lima0 (vzNAT)
# carries the VM's own address.
conf=/etc/avahi/avahi-daemon.conf
sed -i -E 's/^#?allow-interfaces=.*/allow-interfaces=lima0/; s/^#?use-ipv6=.*/use-ipv6=no/' "$conf"
grep -q '^allow-interfaces=lima0$' "$conf"
grep -q '^use-ipv6=no$' "$conf"
systemctl enable avahi-daemon
systemctl restart avahi-daemon

# Lima forwards UDP listeners that exist when its guest agent connects to the
# host, ignore rule or not. chronyd's command port (localhost:323) is the only
# one; chronyc uses the Unix socket instead.
if [ -d /etc/chrony/conf.d ]; then
  echo "cmdport 0" > /etc/chrony/conf.d/lima-ai.conf
  systemctl try-restart chrony
fi

mkdir -p "$(dirname "$marker")"
touch "$marker"
