#!/usr/bin/env bash
# Outer launcher for the Linux Nuitka split layout.
# Deploy root layout:
#   AIPromptBridge              ← this script
#   bin/AIPromptBridge_Internal ← Nuitka standalone binary
#   bin/…                       ← Nuitka .dist contents
#
# Sets CWD-relative config by always invoking the internal binary with
# --launched-mode=console (required by main.setup_workspace).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INTERNAL="${ROOT}/bin/AIPromptBridge_Internal"

if [[ ! -x "${INTERNAL}" ]]; then
  echo "❌ Could not find executable internal binary at:" >&2
  echo "   ${INTERNAL}" >&2
  echo "Extract the full release tarball so bin/ sits next to this launcher." >&2
  exit 1
fi

exec "${INTERNAL}" --launched-mode=console "$@"
