#!/usr/bin/env bash
set -euo pipefail

ORIGINAL_ARGS=("$@")
SELF_REEXEC_DONE="${SOR_INSTALL_SELF_REEXEC_DONE:-0}"

usage() {
  cat <<'EOF'
SimpleOpenRoad installer

Usage:
  install.sh [--repo <owner/repo>] [--version <tag>] [--ref <git-ref>] [--arch <x86_64|arm64>] [--python <binary>] [--install-dir <path>] [--bin-dir <path>] [--yes]

Options:
  --repo        GitHub repository in owner/repo format (default: FHRha/SimpleOpenRoad)
  --version     Release tag (default: latest release tag)
  --ref         Install source archive from a Git ref/branch instead of a release
  --channel     Release channel: stable or prerelease (default: stable)
  --arch        Target archive architecture (default: auto-detect from uname -m)
  --python      Preferred Python binary (must be >= 3.11)
  --install-dir Target install directory (default: ~/.local/share/simple-open-road, or /usr/local/share/simple-open-road for root)
  --bin-dir     Directory for wrapper binary (default: ~/.local/bin)
  --yes, -y     Run non-interactively and allow dependency installation
  -h, --help    Show this help

Examples:
  curl -fsSL https://raw.githubusercontent.com/FHRha/SimpleOpenRoad/main/install.sh | bash
  curl -fsSL https://raw.githubusercontent.com/FHRha/SimpleOpenRoad/main/install.sh | bash -s -- --version v0.1.0
EOF
}

BACKGROUND_MODE=""
STATUS_HINT=""
PYTHON_BIN=""
ASSUME_YES=0

confirm_apt_install() {
  local message="$1"
  local answer=""

  if [[ "${ASSUME_YES}" -eq 1 ]]; then
    return 0
  fi

  if [[ ! -t 0 && ! -r /dev/tty ]]; then
    echo "${message}" >&2
    echo "Dependency installation requires confirmation." >&2
    echo "Rerun interactively, install dependencies manually, or pass --yes." >&2
    return 1
  fi

  printf "%s [y/N]: " "${message}" >/dev/tty
  read -r answer </dev/tty || true
  case "${answer}" in
    y|Y|yes|YES)
      return 0
      ;;
    *)
      echo "Dependency installation skipped by user." >&2
      return 1
      ;;
  esac
}

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

try_install_supported_python_with_apt() {
  local candidate=""

  if [[ "${EUID}" -ne 0 ]]; then
    return 1
  fi
  if ! command -v apt-get >/dev/null 2>&1; then
    return 1
  fi

  if ! confirm_apt_install "Python >= 3.11 was not found. Install Python and venv packages with apt now?"; then
    return 1
  fi

  echo "Installing supported Python runtime via apt..."
  apt-get update

  if DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv >/dev/null 2>&1; then
    if python_is_supported "python3"; then
      PYTHON_BIN="python3"
      return 0
    fi
  fi

  for candidate in python3.13 python3.12 python3.11; do
    echo "Trying ${candidate}..."
    if DEBIAN_FRONTEND=noninteractive apt-get install -y "${candidate}" "${candidate}-venv" >/dev/null 2>&1; then
      if python_is_supported "${candidate}"; then
        PYTHON_BIN="${candidate}"
        return 0
      fi
    fi
  done

  return 1
}

python_major_minor() {
  local bin="$1"
  "${bin}" - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
}

python_supports_venv() {
  local bin="$1"
  local temp_venv=""
  temp_venv="$(mktemp -d "${TMPDIR:-/tmp}/simple-open-road-venv-check.XXXXXX")"
  rm -rf "${temp_venv}"
  if "${bin}" -m venv "${temp_venv}" >/dev/null 2>&1; then
    rm -rf "${temp_venv}"
    return 0
  fi
  rm -rf "${temp_venv}"
  return 1
}

try_install_python_venv_with_apt() {
  local bin="$1"
  local version=""

  if [[ "${EUID}" -ne 0 ]]; then
    return 1
  fi
  if ! command -v apt-get >/dev/null 2>&1; then
    return 1
  fi

  version="$(python_major_minor "${bin}")"
  if ! confirm_apt_install "Python venv/pip support is missing for ${bin}. Install python${version}-venv with apt now?"; then
    return 1
  fi

  echo "Python venv support is missing for ${bin}. Installing python${version}-venv via apt..."
  apt-get update
  if DEBIAN_FRONTEND=noninteractive apt-get install -y "python${version}-venv"; then
    return 0
  fi

  echo "Could not install python${version}-venv; trying generic python3-venv..."
  DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv
}

ensure_python_venv_available() {
  if python_supports_venv "${PYTHON_BIN}"; then
    return 0
  fi

  if try_install_python_venv_with_apt "${PYTHON_BIN}" && python_supports_venv "${PYTHON_BIN}"; then
    return 0
  fi

  local version=""
  version="$(python_major_minor "${PYTHON_BIN}" || true)"
  echo "Python runtime '${PYTHON_BIN}' is available, but venv/ensurepip is missing." >&2
  if [[ -n "${version}" ]]; then
    echo "Install python${version}-venv, then rerun the installer." >&2
    echo "Example: apt install python${version}-venv" >&2
  else
    echo "Install the matching python3-venv package, then rerun the installer." >&2
  fi
  echo "Alternatively pass --python <binary> that already supports: python -m venv." >&2
  return 1
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

  if try_install_supported_python_with_apt; then
    return 0
  fi

  echo "Python >= 3.11 was not found." >&2
  echo "Install python3.11+ and the matching python3-venv package, or run installer with --python <binary>." >&2
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

normalize_release_channel() {
  local value="${1:-stable}"
  case "${value}" in
    stable|prerelease)
      echo "${value}"
      ;;
    *)
      echo "Unsupported --channel value: ${value}" >&2
      echo "Supported values: stable, prerelease" >&2
      exit 1
      ;;
  esac
}

current_script_path() {
  local script_dir=""
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
  printf '%s/%s\n' "${script_dir}" "$(basename "${BASH_SOURCE[0]}")"
}

maybe_reexec_from_temp_copy() {
  local script_path=""
  local install_script_path=""
  local temp_script=""

  if [[ "${SELF_REEXEC_DONE}" == "1" ]]; then
    return
  fi

  script_path="$(current_script_path)"
  install_script_path="${INSTALL_DIR%/}/install.sh"
  if [[ "${script_path}" != "${install_script_path}" ]]; then
    return
  fi

  temp_script="$(mktemp "${TMPDIR:-/tmp}/simple-open-road-installer.XXXXXX.sh")"
  cp "${script_path}" "${temp_script}"
  chmod +x "${temp_script}"
  exec env SOR_INSTALL_SELF_REEXEC_DONE=1 bash "${temp_script}" "${ORIGINAL_ARGS[@]}"
}

extract_release_tag_for_channel() {
  local channel="$1"
  "${PYTHON_BIN}" -c '
import json
import sys

channel = sys.argv[1]
payload = json.load(sys.stdin)

if isinstance(payload, dict):
    tag = payload.get("tag_name")
    if isinstance(tag, str) and tag.strip():
        print(tag.strip())
    raise SystemExit(0)

if isinstance(payload, list):
    for item in payload:
        if not isinstance(item, dict):
            continue
        is_prerelease = bool(item.get("prerelease"))
        if channel == "prerelease" and not is_prerelease:
            continue
        if channel == "stable" and is_prerelease:
            continue
        tag = item.get("tag_name")
        if isinstance(tag, str) and tag.strip():
            print(tag.strip())
            raise SystemExit(0)
' "$channel"
}

wheelhouse_can_install() {
  local wheelhouse_dir="$1"
  "${INSTALL_DIR}/.venv/bin/python" -m pip install \
    --dry-run \
    --no-index \
    --find-links "${wheelhouse_dir}" \
    simple-open-road >/dev/null 2>&1
}

prompt_release_channel() {
  local selected="stable"
  if [[ -t 0 ]]; then
    printf "Install channel [stable/prerelease] (default: stable): " >/dev/tty
    read -r selected </dev/tty || true
  elif [[ -r /dev/tty ]]; then
    printf "Install channel [stable/prerelease] (default: stable): " >/dev/tty
    read -r selected </dev/tty || true
  fi
  selected="${selected:-stable}"
  normalize_release_channel "${selected}"
}

resolve_release_tag() {
  local channel="$1"
  local latest_json=""
  local releases_json=""
  local tag=""

  if [[ "${channel}" == "stable" ]]; then
    latest_json="$(curl -sSL "https://api.github.com/repos/${REPO}/releases/latest" || true)"
    tag="$(printf '%s' "${latest_json}" | extract_release_tag_for_channel stable || true)"
    if [[ -n "${tag}" ]]; then
      echo "${tag}"
      return 0
    fi
  fi

  releases_json="$(curl -sSL "https://api.github.com/repos/${REPO}/releases?per_page=20" || true)"
  tag="$(printf '%s' "${releases_json}" | extract_release_tag_for_channel "${channel}" || true)"
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
      PATH="${BIN_DIR}:${PATH}" "${BIN_DIR}/sor" service install --mode system --config-path "${config_path}" --no-summary
      echo "Service mode: system"
      BACKGROUND_MODE="systemd-system"
      STATUS_HINT="${BIN_DIR}/sor service status --mode system"
    else
      PATH="${BIN_DIR}:${PATH}" "${BIN_DIR}/sor" service install --mode user --config-path "${config_path}" --no-summary
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

print_final_summary() {
  cat <<EOF
+------------------------------------------------------------------+
| Thank you for installing SimpleOpenRoad                          |
+------------------------------------------------------------------+
| Open panel: sor                                                  |
|                                                                  |
| Quick guide:                                                     |
| 1. Quick setup -> Show connection guide                          |
|    Check Base URL and model aliases for plugins                  |
| 2. Gateway access -> Show connection details                     |
|    Copy MASTER_API_KEY and run the automatic API check           |
| 3. Providers and keys -> Add provider key (wizard)               |
|    Add your provider keys before real use                        |
| 4. Diagnostics -> Troubleshooting guide                          |
|    Verify install path/version if something looks wrong          |
|                                                                  |
| Binary: ${BIN_DIR}/sor                                           |
| Install dir: ${INSTALL_DIR}                                      |
| Config: ${INSTALL_DIR}/config/config.yaml                        |
+------------------------------------------------------------------+
EOF
}

preserve_existing_state() {
  PRESERVE_DIR="${TMP_DIR}/preserve"
  mkdir -p "${PRESERVE_DIR}"

  if [[ -f "${INSTALL_DIR}/.env" ]]; then
    mkdir -p "${PRESERVE_DIR}"
    cp "${INSTALL_DIR}/.env" "${PRESERVE_DIR}/.env"
  fi

  if [[ -f "${INSTALL_DIR}/config/config.yaml" ]]; then
    mkdir -p "${PRESERVE_DIR}/config"
    cp "${INSTALL_DIR}/config/config.yaml" "${PRESERVE_DIR}/config/config.yaml"
  fi

  if [[ -d "${INSTALL_DIR}/data" ]]; then
    mkdir -p "${PRESERVE_DIR}"
    cp -R "${INSTALL_DIR}/data" "${PRESERVE_DIR}/data"
  fi
}

restore_existing_state() {
  if [[ -f "${PRESERVE_DIR}/.env" ]]; then
    cp "${PRESERVE_DIR}/.env" "${INSTALL_DIR}/.env"
  fi

  if [[ -f "${PRESERVE_DIR}/config/config.yaml" ]]; then
    mkdir -p "${INSTALL_DIR}/config"
    cp "${PRESERVE_DIR}/config/config.yaml" "${INSTALL_DIR}/config/config.yaml"
  fi

  if [[ -d "${PRESERVE_DIR}/data" ]]; then
    rm -rf "${INSTALL_DIR}/data"
    cp -R "${PRESERVE_DIR}/data" "${INSTALL_DIR}/data"
  fi
}

extract_install_dir_from_wrapper() {
  local wrapper="$1"
  local target=""
  if [[ ! -f "${wrapper}" ]]; then
    return 1
  fi

  target="$(sed -n 's/^exec "\(.*\)\/\.venv\/bin\/sor" .*$/\1/p' "${wrapper}" | head -n1)"
  if [[ -z "${target}" ]]; then
    target="$(sed -n 's/^cd "\(.*\)"$/\1/p' "${wrapper}" | head -n1)"
  fi
  if [[ -n "${target}" && -d "${target}" ]]; then
    echo "${target}"
    return 0
  fi

  return 1
}

detect_existing_install_dir() {
  local wrapper=""
  local detected=""

  for wrapper in "${BIN_DIR}/sor" "$(command -v sor 2>/dev/null || true)" "/usr/local/bin/sor" "${HOME}/.local/bin/sor"; do
    if [[ -z "${wrapper}" ]]; then
      continue
    fi
    detected="$(extract_install_dir_from_wrapper "${wrapper}" || true)"
    if [[ -n "${detected}" ]]; then
      echo "${detected}"
      return 0
    fi
  done

  return 1
}

if [[ "${OSTYPE:-}" != linux* ]]; then
  echo "This installer currently supports Linux only." >&2
  exit 1
fi

DEFAULT_REPO="FHRha/SimpleOpenRoad"
REPO="${DEFAULT_REPO}"
TAG=""
SOURCE_REF=""
RELEASE_CHANNEL="stable"
RELEASE_CHANNEL_EXPLICIT=0
ARCH=""
INSTALL_DIR="${HOME}/.local/share/simple-open-road"
BIN_DIR="${HOME}/.local/bin"
INSTALL_DIR_EXPLICIT=0
BIN_DIR_EXPLICIT=0

# Root installs should expose CLI globally by default.
if [[ "${EUID}" -eq 0 ]] && [[ -d "/usr/local/bin" ]] && [[ -w "/usr/local/bin" ]]; then
  BIN_DIR="/usr/local/bin"
  if [[ -d "/usr/local/share" ]] && [[ -w "/usr/local/share" ]]; then
    INSTALL_DIR="/usr/local/share/simple-open-road"
  fi
fi

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
    --ref)
      SOURCE_REF="$2"
      shift 2
      ;;
    --channel)
      RELEASE_CHANNEL="$2"
      RELEASE_CHANNEL_EXPLICIT=1
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
      INSTALL_DIR_EXPLICIT=1
      shift 2
      ;;
    --bin-dir)
      BIN_DIR="$2"
      BIN_DIR_EXPLICIT=1
      shift 2
      ;;
    --yes|-y)
      ASSUME_YES=1
      shift
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

RELEASE_CHANNEL="$(normalize_release_channel "${RELEASE_CHANNEL}")"

if [[ "${INSTALL_DIR_EXPLICIT}" -eq 0 ]]; then
  EXISTING_INSTALL_DIR="$(detect_existing_install_dir || true)"
  if [[ -n "${EXISTING_INSTALL_DIR}" ]]; then
    INSTALL_DIR="${EXISTING_INSTALL_DIR}"
    echo "Detected existing install directory: ${INSTALL_DIR}"
  fi
fi

if [[ -n "${ARCH}" ]]; then
  ARCH="$(normalize_arch "${ARCH}")"
else
  ARCH="$(detect_arch)"
fi

if [[ -n "${TAG}" && -n "${SOURCE_REF}" ]]; then
  echo "Use either --version or --ref, not both." >&2
  exit 1
fi

if [[ -z "${TAG}" && -z "${SOURCE_REF}" && "${RELEASE_CHANNEL_EXPLICIT}" -eq 0 ]]; then
  RELEASE_CHANNEL="$(prompt_release_channel)"
fi

resolve_python_bin
ensure_python_venv_available

echo "Using Python runtime: ${PYTHON_BIN}"

maybe_reexec_from_temp_copy

if [[ -z "${TAG}" && -z "${SOURCE_REF}" ]]; then
  TAG="$(resolve_release_tag "${RELEASE_CHANNEL}" || true)"
fi

if [[ -z "${TAG}" && -z "${SOURCE_REF}" ]]; then
  echo "Unable to resolve release tag for ${REPO}." >&2
  echo "Create or publish at least one ${RELEASE_CHANNEL} release, or pass --version <tag>." >&2
  exit 1
fi

if [[ -n "${SOURCE_REF}" ]]; then
  SAFE_REF="${SOURCE_REF//\//-}"
  VERSION="${SAFE_REF}"
  ARCHIVE_NAME="simple-open-road-source-${SAFE_REF}.tar.gz"
  ARCHIVE_URL="https://github.com/${REPO}/archive/${SOURCE_REF}.tar.gz"
  echo "Installing source ref: ${SOURCE_REF}"
else
  VERSION="${TAG#v}"
  ARCHIVE_NAME="simple-open-road-${VERSION}-linux-${ARCH}.tar.gz"
  ARCHIVE_URL="https://github.com/${REPO}/releases/download/${TAG}/${ARCHIVE_NAME}"
  echo "Installing ${RELEASE_CHANNEL} release: ${TAG}"
fi

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
if [[ -n "${SOURCE_REF}" ]]; then
  EXTRACTED_DIR="$(find "${TMP_DIR}" -mindepth 1 -maxdepth 1 -type d | head -n1)"
else
  EXTRACTED_DIR="${TMP_DIR}/simple-open-road-${VERSION}-linux-${ARCH}"
fi

if [[ ! -d "${EXTRACTED_DIR}" ]]; then
  echo "Archive layout is invalid: ${EXTRACTED_DIR} not found." >&2
  exit 1
fi

mkdir -p "${INSTALL_DIR}" "${BIN_DIR}"
preserve_existing_state
cp -R "${EXTRACTED_DIR}/." "${INSTALL_DIR}/"
restore_existing_state
echo "Preserved user state: .env, config/config.yaml, data/"

if [[ ! -f "${INSTALL_DIR}/config/config.yaml" ]]; then
  cp "${INSTALL_DIR}/config/config.example.yaml" "${INSTALL_DIR}/config/config.yaml"
fi

echo "Creating virtual environment"
if [[ -x "${INSTALL_DIR}/.venv/bin/python" ]]; then
  if "${INSTALL_DIR}/.venv/bin/python" - <<'PY' >/dev/null 2>&1
import sys
import pip
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
  then
    echo "Reusing existing virtual environment"
  else
    echo "Existing virtual environment is incomplete or unsupported; recreating"
    rm -rf "${INSTALL_DIR}/.venv"
    "${PYTHON_BIN}" -m venv "${INSTALL_DIR}/.venv"
  fi
else
  "${PYTHON_BIN}" -m venv "${INSTALL_DIR}/.venv"
fi

if ! "${INSTALL_DIR}/.venv/bin/python" - <<'PY' >/dev/null 2>&1
import sys
import pip
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY
then
  echo "Created virtual environment is incomplete, missing pip, or using Python < 3.11." >&2
  echo "Remove ${INSTALL_DIR}/.venv and rerun installer with --python <python3.11+ binary>." >&2
  exit 1
fi

echo "Installing SimpleOpenRoad"
export PIP_NO_INPUT=1
export PIP_DISABLE_PIP_VERSION_CHECK=1
if [[ -d "${INSTALL_DIR}/wheelhouse" ]]; then
  if wheelhouse_can_install "${INSTALL_DIR}/wheelhouse"; then
    echo "Installing package from bundled wheelhouse"
    "${INSTALL_DIR}/.venv/bin/python" -m pip install \
      --no-index \
      --find-links "${INSTALL_DIR}/wheelhouse" \
      --upgrade \
      --force-reinstall \
      simple-open-road
  else
    echo "Bundled wheelhouse is incomplete or incompatible; installing with PyPI fallback"
    "${INSTALL_DIR}/.venv/bin/python" -m pip install \
      --retries 3 \
      --timeout 60 \
      --prefer-binary \
      --find-links "${INSTALL_DIR}/wheelhouse" \
      --upgrade \
      --force-reinstall \
      simple-open-road
  fi
else
  echo "Bundled wheelhouse not found; installing dependencies from PyPI"
  "${INSTALL_DIR}/.venv/bin/python" -m pip install --retries 3 --timeout 60 --prefer-binary -e "${INSTALL_DIR}"
fi

cat > "${BIN_DIR}/sor" <<EOF
#!/usr/bin/env bash
cd "${INSTALL_DIR}"
exec "${INSTALL_DIR}/.venv/bin/sor" "\$@"
EOF
chmod +x "${BIN_DIR}/sor"

setup_background_runtime

print_final_summary

if ! command -v sor >/dev/null 2>&1; then
  echo "Note: 'sor' is not available in PATH for this shell."
  echo "Run: export PATH=\"${BIN_DIR}:\$PATH\""
fi
