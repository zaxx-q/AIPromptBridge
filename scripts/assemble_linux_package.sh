#!/usr/bin/env bash
# Assemble the Linux Nuitka standalone tree into a release tarball.
#
# Expects Nuitka output at build_internal/main.dist/ (Nuitka-Action default
# when compiling main.py) containing AIPromptBridge_Internal (or main.bin).
#
# Usage:
#   ./scripts/assemble_linux_package.sh <VERSION> [OUTPUT_DIR]
#   VERSION e.g. v7.0.0  →  AIPromptBridge-v7.0.0-linux-x86_64.tar.gz
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="${1:-}"
OUT_DIR="${2:-${ROOT}}"

if [[ -z "${VERSION}" ]]; then
  echo "Usage: $0 <VERSION> [OUTPUT_DIR]" >&2
  exit 2
fi

# Normalize leading v
if [[ "${VERSION}" != v* && "${VERSION}" != V* ]]; then
  VERSION="v${VERSION}"
fi

DIST_SRC=""
for candidate in \
  "${ROOT}/build_internal/main.dist" \
  "${ROOT}/build_internal/AIPromptBridge_Internal.dist" \
  "${ROOT}/main.dist"
do
  if [[ -d "${candidate}" ]]; then
    DIST_SRC="${candidate}"
    break
  fi
done

if [[ -z "${DIST_SRC}" ]]; then
  echo "❌ Nuitka dist directory not found under build_internal/" >&2
  echo "   Looked for main.dist / AIPromptBridge_Internal.dist" >&2
  exit 1
fi

STAGE_NAME="AIPromptBridge-${VERSION}-linux-x86_64"
STAGE="${OUT_DIR}/${STAGE_NAME}"
rm -rf "${STAGE}"
mkdir -p "${STAGE}/bin"

echo "→ Copying Nuitka dist from ${DIST_SRC}"
cp -a "${DIST_SRC}/." "${STAGE}/bin/"

# Normalize internal binary name
INTERNAL_CANDIDATES=(
  "${STAGE}/bin/AIPromptBridge_Internal"
  "${STAGE}/bin/main.bin"
  "${STAGE}/bin/main"
)
INTERNAL=""
for c in "${INTERNAL_CANDIDATES[@]}"; do
  if [[ -f "${c}" ]]; then
    INTERNAL="${c}"
    break
  fi
done

if [[ -z "${INTERNAL}" ]]; then
  # Last resort: first executable file in bin/
  while IFS= read -r -d '' f; do
    if [[ -x "${f}" && -f "${f}" ]]; then
      INTERNAL="${f}"
      break
    fi
  done < <(find "${STAGE}/bin" -maxdepth 1 -type f -print0)
fi

if [[ -z "${INTERNAL}" ]]; then
  echo "❌ Could not locate Nuitka binary inside ${STAGE}/bin" >&2
  ls -la "${STAGE}/bin" >&2 || true
  exit 1
fi

if [[ "$(basename "${INTERNAL}")" != "AIPromptBridge_Internal" ]]; then
  echo "→ Renaming $(basename "${INTERNAL}") → AIPromptBridge_Internal"
  mv "${INTERNAL}" "${STAGE}/bin/AIPromptBridge_Internal"
fi
chmod +x "${STAGE}/bin/AIPromptBridge_Internal"

# Outer launcher + README
install -m 755 "${ROOT}/scripts/linux_launcher.sh" "${STAGE}/AIPromptBridge"
install -m 644 "${ROOT}/scripts/README-linux.txt" "${STAGE}/README-linux.txt"

# Optional icon at root for convenience (also lives under bin/ from Nuitka data)
if [[ -f "${ROOT}/icon.ico" ]]; then
  cp -f "${ROOT}/icon.ico" "${STAGE}/icon.ico" || true
fi

TARBALL="${OUT_DIR}/${STAGE_NAME}.tar.gz"
echo "→ Creating ${TARBALL}"
tar -C "${OUT_DIR}" -czf "${TARBALL}" "${STAGE_NAME}"

echo "✓ Linux package ready: ${TARBALL}"
echo "  Extract and run: tar -xzf ${STAGE_NAME}.tar.gz && ./${STAGE_NAME}/AIPromptBridge --show-console"

# Export path for CI
if [[ -n "${GITHUB_ENV:-}" ]]; then
  echo "LINUX_ASSET_PATH=${TARBALL}" >> "${GITHUB_ENV}"
  echo "LINUX_ASSET_NAME=${STAGE_NAME}.tar.gz" >> "${GITHUB_ENV}"
fi
