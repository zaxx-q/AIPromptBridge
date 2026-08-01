#!/usr/bin/env bash
# Outer launcher for the Linux Nuitka split layout.
# Deploy root layout:
#   AIPromptBridge              ← this script
#   aipb_trigger.py             ← stdlib-only IPC client (fast --trigger path)
#   bin/AIPromptBridge_Internal ← Nuitka standalone binary
#   bin/…                       ← Nuitka .dist contents
#
# Sets CWD-relative config by always invoking the internal binary with
# --launched-mode=console (required by main.setup_workspace).
#
# Symlinks are resolved so PATH installs work, e.g.:
#   ~/.local/bin/AIPromptBridge → ~/.local/AIPromptBridge/AIPromptBridge
# Without resolving, ROOT would be ~/.local/bin and bin/ would be missing.
#
# --trigger never starts the ~100MB Nuitka binary: compositor binds need
# tens of milliseconds, not multi-second cold starts.
set -euo pipefail

# Linux (GNU coreutils): readlink -f canonicalizes symlinks to the real file.
_LAUNCHER="$(readlink -f "${BASH_SOURCE[0]}")"
ROOT="$(cd "$(dirname "${_LAUNCHER}")" && pwd)"
INTERNAL="${ROOT}/bin/AIPromptBridge_Internal"
TRIGGER_CLIENT="${ROOT}/aipb_trigger.py"

# ─── Fast IPC client (no Nuitka) ───────────────────────────────────────────
if [[ "${1:-}" == "--trigger" ]] || [[ "${1:-}" == --trigger=* ]]; then
  if [[ ! -f "${TRIGGER_CLIENT}" ]]; then
    echo "❌ Fast trigger client missing: ${TRIGGER_CLIENT}" >&2
    echo "   Re-extract the release package (aipb_trigger.py sits next to this launcher)." >&2
    exit 1
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    echo "❌ python3 not found on PATH (needed for --trigger without starting the full app)." >&2
    echo "   Install python3, or start the full app and use a direct socket client." >&2
    exit 1
  fi
  # Pass through remaining args as-is (supports --trigger NAME and --trigger=NAME).
  exec python3 "${TRIGGER_CLIENT}" "$@"
fi

if [[ ! -x "${INTERNAL}" ]]; then
  echo "❌ Could not find executable internal binary at:" >&2
  echo "   ${INTERNAL}" >&2
  echo "Extract the full release tarball so bin/ sits next to this launcher." >&2
  exit 1
fi

exec "${INTERNAL}" --launched-mode=console "$@"
