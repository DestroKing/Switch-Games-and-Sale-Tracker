#!/usr/bin/env bash
# switch-tracker bootstrap — macOS, Linux, WSL
#
# Installs everything the tracker needs and leaves you at a working probe run.
# Safe to re-run: every step checks before it acts.

set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()  { printf '  \033[32m✓\033[0m %s\n' "$*"; }

# ---------------------------------------------------------------- 1. Bun
say "1/4  Bun runtime"
if command -v bun >/dev/null 2>&1; then
  ok "already installed ($(bun --version))"
else
  echo "  installing from bun.sh…"
  curl -fsSL https://bun.sh/install | bash
  # The installer edits your shell profile, which won't affect this process.
  export BUN_INSTALL="${BUN_INSTALL:-$HOME/.bun}"
  export PATH="$BUN_INSTALL/bin:$PATH"
  ok "installed ($(bun --version))"
  NEEDS_RELOAD=1
fi

# ------------------------------------------------------------ 2. packages
say "2/4  Project dependencies"
bun install
ok "done"

# ------------------------------------------------------------ 3. Chromium
say "3/4  Chromium for Playwright (~300 MB, one time)"
if bunx playwright install chromium 2>&1 | tee /tmp/pw-install.log | grep -qi "is already installed"; then
  ok "already present"
else
  ok "downloaded"
fi

# On bare Linux (VM, container, WSL) Chromium needs system libraries. This
# needs sudo, so it's offered rather than forced.
if [[ "$(uname -s)" == "Linux" ]]; then
  if ! bunx playwright install-deps chromium --dry-run >/dev/null 2>&1; then
    echo
    echo "  Linux detected. Chromium may need system libraries."
    echo "  If the browser fails to launch later, run:"
    echo "      sudo bunx playwright install-deps chromium"
  fi
fi

# ------------------------------------------------------------- 4. verify
say "4/4  Probing stores"
bun run probe

say "Setup complete."
echo "  Next:  edit src/config/stores.ts to match the DETECTED column above,"
echo "         then run:  bun run collect"
if [[ "${NEEDS_RELOAD:-0}" == "1" ]]; then
  echo
  echo "  Note: open a new terminal (or 'source ~/.bashrc') before using 'bun' directly."
fi
