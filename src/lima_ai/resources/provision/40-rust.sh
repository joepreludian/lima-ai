#!/bin/bash
# Rust stable through rustup, with clippy and rustfmt.
set -euo pipefail
marker="$HOME/.local/state/lima-ai/40-rust.done"
[ -e "$marker" ] && exit 0

curl --proto '=https' --tlsv1.2 -fsSL https://sh.rustup.rs \
  | sh -s -- -y --no-modify-path --default-toolchain stable --component clippy --component rustfmt

mkdir -p "$(dirname "$marker")"
touch "$marker"
