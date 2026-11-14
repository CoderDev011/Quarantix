#!/usr/bin/env bash
# Install the user-level dev tools AgentWall needs (inside WSL, no sudo):
#   uv   - Python package and version manager (official Astral installer)
#   pnpm - major 10, via npm into ~/.local (corepack failed to load pnpm 12)
# Safe to re-run: skips tools that are already present.
set -euo pipefail

mkdir -p "$HOME/.local/bin"
export PATH="$HOME/.local/bin:$PATH"

if command -v uv >/dev/null 2>&1; then
  echo "uv already installed: $(uv --version)"
else
  installer="$(mktemp)"
  curl -LsSf https://astral.sh/uv/install.sh -o "$installer"
  head -1 "$installer" | grep -q '^#!/bin/sh' || { echo "unexpected uv installer content" >&2; exit 1; }
  sh "$installer"
  rm -f "$installer"
fi

if pnpm --version >/dev/null 2>&1; then
  echo "pnpm already installed: $(pnpm --version)"
else
  # Remove a broken corepack shim if an earlier attempt left one.
  corepack disable --install-directory "$HOME/.local/bin" pnpm 2>/dev/null || true
  npm install --global --prefix "$HOME/.local" pnpm@10
  echo "pnpm installed: $(pnpm --version)"
fi

echo "Done. If uv or pnpm is not found in a new shell, add \$HOME/.local/bin to PATH."
