#!/usr/bin/env bash
set -euo pipefail

PROFILE="${1:-core}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${ROOT}/.venv-build"
TOOLS_DIR="${ROOT}/.tools"
BUILD_ARGS=(scripts/build_release.py --profile "${PROFILE}" --mode all)

if [[ "${PROFILE}" != "core" && "${PROFILE}" != "enterprise" ]]; then
  echo "usage: ./scripts/build_linux.sh [core|enterprise]" >&2
  exit 1
fi

if [[ ! -d "${VENV}" ]]; then
  python3 -m venv "${VENV}"
fi

PYTHON="${VENV}/bin/python"
"${PYTHON}" -m pip install --upgrade pip

if [[ "${PROFILE}" == "enterprise" ]]; then
  "${PYTHON}" -m pip install --upgrade ".[release,observability,guard,arrow,wasm,gpu,atheria]"
else
  "${PYTHON}" -m pip install --upgrade ".[release]"
fi

mkdir -p "${TOOLS_DIR}"
if ! command -v appimagetool >/dev/null 2>&1; then
  APPIMAGETOOL="${TOOLS_DIR}/appimagetool"
  if [[ ! -x "${APPIMAGETOOL}" ]]; then
    ARCH="$(uname -m)"
    case "${ARCH}" in
      x86_64) APPIMAGE_ASSET="appimagetool-x86_64.AppImage" ;;
      aarch64|arm64) APPIMAGE_ASSET="appimagetool-aarch64.AppImage" ;;
      *)
        echo "unsupported architecture for automatic appimagetool bootstrap: ${ARCH}" >&2
        exit 1
        ;;
    esac
    curl -L "https://github.com/AppImage/appimagetool/releases/download/continuous/${APPIMAGE_ASSET}" -o "${APPIMAGETOOL}"
    chmod +x "${APPIMAGETOOL}"
  fi
  export PATH="${TOOLS_DIR}:${PATH}"
fi

if [[ -n "${SOURCE_DATE_EPOCH:-}" ]]; then
  BUILD_ARGS+=(--source-date-epoch "${SOURCE_DATE_EPOCH}")
fi

"${PYTHON}" "${BUILD_ARGS[@]}"
