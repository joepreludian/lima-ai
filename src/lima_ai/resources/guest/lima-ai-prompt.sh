# lima-ai's bash prompt:  l-ai <fqdn> <workspace> <folder> (<branch>)$
# Installed by lima-ai into ~/.config/lima-ai/prompt.sh and sourced from the
# end of ~/.bashrc, so it replaces the stock prompt. It leaves the prompt alone
# in non-interactive shells and when the instance file is missing.
case $- in *i*) ;; *) return 0 2>/dev/null || exit 0 ;; esac
[ -f "$HOME/.config/lima-ai/instance" ] || return 0

. "$HOME/.config/lima-ai/instance"
LIMA_AI_FQDN="$(hostname).local"

# " (branch)", " (short commit)" when HEAD is detached, nothing outside a repository.
__lima_ai_branch() {
  local ref
  if ref="$(git symbolic-ref -q --short HEAD 2>/dev/null)" || ref="$(git rev-parse --short HEAD 2>/dev/null)"; then
    printf ' (%s)' "$ref"
  fi
}

# Colors sit inside \[ \] so bash does not count them when editing the line.
PS1='\[\e[1;33m\]l-ai\[\e[0m\] \[\e[36m\]${LIMA_AI_FQDN}\[\e[0m\] \[\e[1;35m\]${LIMA_AI_WORKSPACE}\[\e[0m\] \[\e[34m\]\w\[\e[0m\]\[\e[32m\]$(__lima_ai_branch)\[\e[0m\]\$ '
