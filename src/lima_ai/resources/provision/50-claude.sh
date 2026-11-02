#!/bin/bash
# Claude Code (native installer) and the shell setup every lima-ai VM shares.
set -euo pipefail
marker="$HOME/.local/state/lima-ai/50-claude.done"
[ -e "$marker" ] && exit 0

curl -fsSL https://claude.ai/install.sh | bash
test -x "$HOME/.local/bin/claude"

cat >> "$HOME/.bashrc" <<'BASHRC'

# >>> lima-ai >>>
export PATH="$HOME/.local/bin:$PATH"
if [ -d "$HOME/.local/share/fnm" ]; then
  export PATH="$HOME/.local/share/fnm:$PATH"
  eval "$(fnm env --use-on-cd --shell bash)"
fi
[ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env"
[ -f "$HOME/.config/lima-ai/env" ] && . "$HOME/.config/lima-ai/env"
alias cc='claude --dangerously-skip-permissions'
# <<< lima-ai <<<
BASHRC

mkdir -p "$(dirname "$marker")"
touch "$marker"
