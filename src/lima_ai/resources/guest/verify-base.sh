#!/bin/bash
# Checks a freshly provisioned dev-base. Runs as the default user; each check
# is announced on stderr so a failure's tail names it.
set -euo pipefail
export PATH="$HOME/.local/bin:$HOME/.local/share/fnm:$PATH"
eval "$(fnm env --shell bash)"
. "$HOME/.cargo/env"

check() {
  echo "--> $*" >&2
  "$@"
}

# The provisioning SSH session predates the docker group membership.
check sg docker -c "docker run --rm hello-world"
check node -v
check cargo -V
check claude --version
check rtk --version
check docker compose version
check docker-backup --version
check sg docker -c "docker-backup doctor"
check avahi-daemon --check
