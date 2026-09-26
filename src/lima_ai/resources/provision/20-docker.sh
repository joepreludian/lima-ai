#!/bin/bash
# Docker Engine and the compose/buildx plugins from Docker's apt repository.
set -euo pipefail
marker="/var/lib/lima-ai/20-docker.done"
[ -e "$marker" ] && exit 0

export DEBIAN_FRONTEND=noninteractive
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${UBUNTU_CODENAME:-$VERSION_CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
usermod -aG docker "$LIMA_CIDATA_USER"
systemctl enable --now docker

mkdir -p "$(dirname "$marker")"
touch "$marker"
