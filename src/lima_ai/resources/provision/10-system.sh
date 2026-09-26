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

mkdir -p "$(dirname "$marker")"
touch "$marker"
