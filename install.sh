#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
SimpleOpenRoad installer

Usage:
  install.sh [--repo <owner/repo>] [--version <tag>] [--arch <x86_64|arm64>] [--python <binary>] [--install-dir <path>] [--bin-dir <path>]

Options:
  --repo        GitHub repository in owner/repo format (default: FHRha/SimpleOpenRoad)
  --version     Release tag (default: latest release tag)
  --arch        Target archive architecture (default: auto-detect from uname -m)
  --python      Preferred Python binary (must be >= 3.11)
  --install-dir Target install directory (default: ~/.local/share/simple-open-road)
  --bin-dir     Directory for wrapper binary (default: ~/.local/bin)
  -h, --help    Show this help

Examples:
  curl -fsSL https://raw.githubusercontent.com/FHRha/SimpleOpenRoad/main/install.sh | bash
  curl -fsSL https://raw.githubusercontent.com/FHRha/SimpleOpenRoad/main/install.sh | bash -s -- --version v0.1.0
EOF
}

BACKGROUND_MODE=""
STATUS_HINT=""
PYTHON_BIN=""

python_is_supported() {
  local bin="$1"
  if ! command -v "${bin}" >/dev/null 2>&1; then
    return 1
  fi

  "${bin}" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
}

try_install_python311_with_apt() {
  if [[ "${EUID}" -ne 0 ]]; then
    return 1
  fi
  if ! command -v apt-get >/dev/null 2>&1; then
    return 1
  fi

  echo "Installing Python 3.11 runtime via apt..."
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y python3.11 python3.11-venv
}

resolve_python_bin() {
  local candidate=""

  if [[ -n "${PYTHON_BIN}" ]]; then
    if python_is_supported "${PYTHON_BIN}"; then
      return 0
    fi
    echo "Provided --python '${PYTHON_BIN}' is not available or is < 3.11." >&2
    return 1
  fi

  for candidate in python3.13 python3.12 python3.11 python3; do
    if python_is_supported "${candidate}"; then
      PYTHON_BIN="${candidate}"
      return 0
    fi
  done

  if try_install_python311_with_apt && python_is_supported "python3.11"; then
    PYTHON_BIN="python3.11"
    return 0
  fi

  echo "Python >= 3.11 was not found." >&2
  echo "Install python3.11 and python3.11-venv, or run installer with --python <binary>." >&2
  return 1
}

detect_arch() {
  local machine
  machine="$(uname -m)"

  case "${machine}" in
    x86_64|amd64)
      echo "x86_64"
      ;;
    aarch64|arm64)
      echo "arm64"
      ;;
    *)
      echo "Unsupported architecture: ${machine}" >&2
      echo "Use --arch to override. Supported values: x86_64, arm64" >&2
      exit 1
      ;;
  esac
}

normalize_arch() {
  local value
  value="${1:-}"
  case "${value}" in
    x86_64|amd64)
      echo "x86_64"
      ;;
    arm64|aarch64)
      echo "arm64"
      ;;
    *)
      echo "Unsupported --arch value: ${value}" >&2
      echo "Supported values: x86_64, arm64" >&2
      exit 1
      ;;
  esac
}

extract_first_tag_name() {
  sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1
}

resolve_release_tag() {
  local latest_json=""
  local releases_json=""
  local tag=""

  latest_json="$(curl -sSL "https://api.github.com/repos/${REPO}/releases/latest" || true)"
  tag="$(printf '%s' "${latest_json}" | extract_first_tag_name)"
  if [[ -n "${tag}" ]]; then
    echo "${tag}"
    return 0
  fi

  releases_json="$(curl -sSL "https://api.github.com/repos/${REPO}/releases?per_page=20" || true)"
  tag="$(printf '%s' "${releases_json}" | extract_first_tag_name)"
  if [[ -n "${tag}" ]]; then
    echo "${tag}"
    return 0
  fi

  return 1
}

setup_background_runtime() {
  local config_path="${INSTALL_DIR}/config/config.yaml"

  if command -v systemctl >/dev/null 2>&1 && [[ -d /run/systemd/system ]]; then
    echo "Configuring background service (systemd)"
    if [[ "${EUID}" -eq 0 ]]; then
      "${BIN_DIR}/sor" service install --mode system --config-path "${config_path}"
      echo "Service mode: system"
      BACKGROUND_MODE="systemd-system"
      STATUS_HINT="${BIN_DIR}/sor service status --mode system"
    else
      "${BIN_DIR}/sor" service install --mode user --config-path "${config_path}"
      echo "Service mode: user"
      BACKGROUND_MODE="systemd-user"
      STATUS_HINT="${BIN_DIR}/sor service status --mode user"
      if command -v loginctl >/dev/null 2>&1; then
        if loginctl enable-linger "${USER}" >/dev/null 2>&1; then
          echo "Enabled linger for ${USER} (service survives logout)."
        else
          echo "Warning: could not enable linger automatically."
          echo "Run manually for logout persistence: sudo loginctl enable-linger ${USER}"
        fi
      fi
    fi
    return
  fi

  echo "systemd not detected; falling back to nohup background process"
  mkdir -p "${INSTALL_DIR}/run"
  nohup "${BIN_DIR}/sor" start --config-path "${config_path}" \
    >"${INSTALL_DIR}/run/sor.out.log" 2>"${INSTALL_DIR}/run/sor.err.log" < /dev/null &
  echo "$!" > "${INSTALL_DIR}/run/sor.pid"
  echo "Background process started with PID $(cat "${INSTALL_DIR}/run/sor.pid")"
  BACKGROUND_MODE="nohup"
  STATUS_HINT="tail -n 100 ${INSTALL_DIR}/run/sor.out.log"
}

if [[ "${OSTYPE:-}" != linux* ]]; then
  echo "This installer currently supports Linux only." >&2
  exit 1
fi

DEFAULT_REPO="FHRha/SimpleOpenRoad"
REPO="${DEFAULT_REPO}"
TAG=""
ARCH=""
INSTALL_DIR="${HOME}/.local/share/simple-open-road"
BIN_DIR="${HOME}/.local/bin"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      REPO="$2"
      shift 2
      ;;
    --version)
      TAG="$2"
      shift 2
      ;;
    --arch)
      ARCH="$2"
      shift 2
      ;;
    --python)
      PYTHON_BIN="$2"
      shift 2
      ;;
    --install-dir)
      INSTALL_DIR="$2"
      shift 2
      ;;
    --bin-dir)
      BIN_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -n "${ARCH}" ]]; then
  ARCH="$(normalize_arch "${ARCH}")"
else
  ARCH="$(detect_arch)"
fi

resolve_python_bin

if [[ -z "${TAG}" ]]; then
  TAG="$(resolve_release_tag || true)"
fi

if [[ -z "${TAG}" ]]; then
  echo "Unable to resolve release tag for ${REPO}." >&2
  echo "Create or publish at least one release, or pass --version <tag>." >&2
  exit 1
fi

VERSION="${TAG#v}"
ARCHIVE_NAME="simple-open-road-${VERSION}-linux-${ARCH}.tar.gz"
ARCHIVE_URL="https://github.com/${REPO}/releases/download/${TAG}/${ARCHIVE_NAME}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

echo "Downloading ${ARCHIVE_URL}"
if ! curl -fL "${ARCHIVE_URL}" -o "${TMP_DIR}/${ARCHIVE_NAME}"; then
  echo "Failed to download release archive: ${ARCHIVE_URL}" >&2
  echo "Check that release ${TAG} contains asset ${ARCHIVE_NAME}, or override with --version/--arch." >&2
  exit 1
fi

echo "Extracting archive"
tar -xzf "${TMP_DIR}/${ARCHIVE_NAME}" -C "${TMP_DIR}"
EXTRACTED_DIR="${TMP_DIR}/simple-open-road-${VERSION}-linux-${ARCH}"

if [[ ! -d "${EXTRACTED_DIR}" ]]; then
  echo "Archive layout is invalid: ${EXTRACTED_DIR} not found." >&2
  exit 1
fi

mkdir -p "${INSTALL_DIR}" "${BIN_DIR}"
cp -R "${EXTRACTED_DIR}/." "${INSTALL_DIR}/"

if [[ ! -f "${INSTALL_DIR}/config/config.yaml" ]]; then
  cp "${INSTALL_DIR}/config/config.example.yaml" "${INSTALL_DIR}/config/config.yaml"
fi

echo "Creating virtual environment"
"${PYTHON_BIN}" -m venv "${INSTALL_DIR}/.venv"

echo "Installing SimpleOpenRoad"
"${INSTALL_DIR}/.venv/bin/python" -m pip install --upgrade pip
"${INSTALL_DIR}/.venv/bin/python" -m pip install -e "${INSTALL_DIR}"

cat > "${BIN_DIR}/sor" <<EOF
#!/usr/bin/env bash
exec "${INSTALL_DIR}/.venv/bin/sor" "\$@"
EOF
chmod +x "${BIN_DIR}/sor"

setup_background_runtime

echo "Installation complete"
echo "Binary: ${BIN_DIR}/sor"
echo "Config: ${INSTALL_DIR}/config/config.yaml"
echo "Architecture: ${ARCH}"
echo "Python binary: ${PYTHON_BIN}"
echo "Background mode: ${BACKGROUND_MODE}"
echo "Status command: ${STATUS_HINT}"
