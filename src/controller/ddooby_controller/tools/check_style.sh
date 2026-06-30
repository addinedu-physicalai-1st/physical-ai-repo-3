#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PACKAGE_DIR}"

echo "[style] Python: pycodestyle"
python3 -m pycodestyle \
  launch \
  modeling \
  scripts \
  tools \
  --config setup.cfg

CLANG_FORMAT_BIN="${CLANG_FORMAT_BIN:-clang-format}"

if ! command -v "${CLANG_FORMAT_BIN}" >/dev/null 2>&1; then
  echo "[style] C++: ${CLANG_FORMAT_BIN} not found; install clang-format to check Google C++ style."
  if [[ "${REQUIRE_CLANG_FORMAT:-false}" == "true" ]]; then
    exit 1
  fi
  exit 0
fi

echo "[style] C++: ${CLANG_FORMAT_BIN} --dry-run"
mapfile -t CPP_FILES < <(
  find include src tools \
    -path '*/openarm_vendor/*' -prune -o \
    -type f \( -name '*.h' -o -name '*.hpp' -o -name '*.cc' -o -name '*.cpp' \) \
    -print
)

if ((${#CPP_FILES[@]} > 0)); then
  "${CLANG_FORMAT_BIN}" --dry-run --Werror "${CPP_FILES[@]}"
fi

echo "[style] OK"
