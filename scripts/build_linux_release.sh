#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
ARCH="${ARCH:-x86_64}"
PLATFORM="${PLATFORM:-linux}"

if [[ $# -gt 0 ]]; then
  VERSION="$1"
else
  VERSION="$(${PYTHON_BIN} - <<'PY'
import pathlib
import tomllib

pyproject = pathlib.Path("pyproject.toml")
data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
print(data["project"]["version"])
PY
)"
fi

VERSION="${VERSION#v}"
RELEASE_NAME="simple-open-road-${VERSION}-${PLATFORM}-${ARCH}"
DIST_DIR="${ROOT_DIR}/dist"
STAGE_DIR="${DIST_DIR}/${RELEASE_NAME}"
ARCHIVE_PATH="${DIST_DIR}/${RELEASE_NAME}.tar.gz"

echo "Building ${ARCHIVE_PATH}"
rm -rf "${STAGE_DIR}" "${ARCHIVE_PATH}"
mkdir -p "${STAGE_DIR}" "${STAGE_DIR}/config"

cp -r "${ROOT_DIR}/app" "${STAGE_DIR}/app"
cp -r "${ROOT_DIR}/docs" "${STAGE_DIR}/docs"
cp "${ROOT_DIR}/pyproject.toml" "${STAGE_DIR}/pyproject.toml"
cp "${ROOT_DIR}/README.md" "${STAGE_DIR}/README.md"
cp "${ROOT_DIR}/install.sh" "${STAGE_DIR}/install.sh"
cp "${ROOT_DIR}/config/config.example.yaml" "${STAGE_DIR}/config/config.example.yaml"

cat > "${STAGE_DIR}/VERSION" <<EOF
${VERSION}
EOF

tar -C "${DIST_DIR}" -czf "${ARCHIVE_PATH}" "${RELEASE_NAME}"
echo "Release archive created: ${ARCHIVE_PATH}"
