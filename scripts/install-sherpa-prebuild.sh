#!/data/data/com.termux/files/usr/bin/bash
# install-sherpa-prebuild.sh — install the android-arm64 sherpa-onnx native prebuild.
#
# sherpa-onnx-node ships no android-arm64 binary on npm, so speech-to-text
# on Termux fails with "Local speech is unavailable for android-arm64".
# The "sherpa-onnx prebuild (Termux android-arm64)" workflow compiles the native
# Node-API addon against bionic/aarch64 on GitHub Actions; this script fetches it,
# installs it into node_modules, and caches it at ~/.dsh/native/android-arm64/sherpa
# so patch_termux.py can restore it after future updates without another download.
#
# Usage:
#   bash scripts/install-sherpa-prebuild.sh                 # latest successful CI run
#   bash scripts/install-sherpa-prebuild.sh --run-id 12345  # a specific CI run
#   bash scripts/install-sherpa-prebuild.sh --file <path>   # a local archive or dir
set -euo pipefail

REPO="${DSH_REPO:-salmanbappi/deepseek-harness}"
WORKFLOW="${DSH_SHERPA_WORKFLOW:-build-termux-sherpa.yml}"
DSH_DIR="${DSH_DIR:-$HOME/deepseek-harness}"
CACHE="$HOME/.dsh/native/android-arm64/sherpa"
RUN_ID=""
LOCAL_FILE=""

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[✓]${NC} $*"; }
info() { echo -e "${CYAN}[*]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[✗]${NC} $*" >&2; }

while [ $# -gt 0 ]; do
    case "$1" in
        --run-id) RUN_ID="${2:?--run-id needs a value}"; shift 2 ;;
        --file)   LOCAL_FILE="${2:?--file needs a path}"; shift 2 ;;
        -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
        *) err "unknown argument: $1"; exit 2 ;;
    esac
done

WORK=$(mktemp -d "${TMPDIR:-/data/data/com.termux/files/usr/tmp}/sherpa-prebuild.XXXXXX")
trap 'rm -rf "$WORK"' EXIT

# ── 1. Obtain the binary bundle ─────────────────────────────────────────────
if [ -n "$LOCAL_FILE" ]; then
    if [ -f "$LOCAL_FILE" ]; then
        info "Unpacking local archive: $LOCAL_FILE"
        tar -xzf "$LOCAL_FILE" -C "$WORK"
        # If it extracted into a subfolder, normalize
        if [ -d "$WORK/sherpa-android-arm64" ]; then
            cp -r "$WORK/sherpa-android-arm64/." "$WORK/"
        fi
    elif [ -d "$LOCAL_FILE" ]; then
        info "Using local directory: $LOCAL_FILE"
        cp -r "$LOCAL_FILE/." "$WORK/"
    else
        err "Path does not exist: $LOCAL_FILE"; exit 1
    fi
else
    # Check if we already have it in cache first
    if [ -f "$CACHE/sherpa-onnx.node" ] && [ -f "$CACHE/libsherpa-onnx-c-api.so" ]; then
        info "Using existing cached build at $CACHE..."
        cp -r "$CACHE/." "$WORK/"
    else
        command -v gh >/dev/null || { err "'gh' is required (pkg install gh)"; exit 1; }
        if [ -z "$RUN_ID" ]; then
            info "Looking up the latest successful $WORKFLOW run in $REPO..."
            RUN_ID=$(gh run list --repo "$REPO" --workflow "$WORKFLOW" \
                --status success --limit 1 --json databaseId -q '.[0].databaseId' 2>/dev/null || true)
            [ -n "$RUN_ID" ] || { err "no successful $WORKFLOW run found — push the workflow and let it build first, or pass --file"; exit 1; }
        fi
        info "Downloading artifact from run $RUN_ID..."
        gh run download "$RUN_ID" --repo "$REPO" -n "sherpa-android-arm64" -D "$WORK/dl"
        cp -r "$WORK/dl/." "$WORK/"
    fi
fi

# ── 2. Sanity-check the binaries ────────────────────────────────────────────
[ -f "$WORK/sherpa-onnx.node" ] || { err "sherpa-onnx.node not found in bundle"; exit 1; }
[ -f "$WORK/libsherpa-onnx-c-api.so" ] || { err "libsherpa-onnx-c-api.so not found in bundle"; exit 1; }
[ -f "$WORK/libonnxruntime.so" ] || { err "libonnxruntime.so not found in bundle"; exit 1; }

DESC=$(file -b "$WORK/sherpa-onnx.node" 2>/dev/null || echo unknown)
case "$DESC" in
    *"ELF 64-bit"*"ARM aarch64"*) ok "sherpa-onnx.node looks right: $DESC" ;;
    *) err "not an aarch64 shared object: $DESC"; exit 1 ;;
esac

# ── 3. Cache the binary bundle ──────────────────────────────────────────────
mkdir -p "$CACHE"
cp "$WORK/sherpa-onnx.node" "$CACHE/"
cp "$WORK"/lib*.so "$CACHE/"
if [ -f "$WORK/manifest.json" ]; then
    cp "$WORK/manifest.json" "$CACHE/"
fi
ok "Cached → $CACHE/"

# ── 4. Install into node_modules ────────────────────────────────────────────
install_into() {
    local dest="$1"
    mkdir -p "$dest"
    cp -f "$WORK/sherpa-onnx.node" "$dest/"
    cp -f "$WORK"/lib*.so "$dest/"
    cat << 'EOF' > "$dest/package.json"
{
  "name": "sherpa-onnx-android-arm64",
  "version": "1.13.8",
  "description": "Prebuilt native binaries for sherpa-onnx on Android arm64",
  "main": "sherpa-onnx.node",
  "os": ["android"],
  "cpu": ["arm64"]
}
EOF
    ok "Installed → ${dest#$HOME/}"
}

# Root node_modules
install_into "$DSH_DIR/node_modules/sherpa-onnx-android-arm64"

# Every sherpa-onnx-node in pnpm store
mapfile -t TARGETS < <(find "$DSH_DIR/node_modules" "$HOME/.dsh" \
    -type d -name "sherpa-onnx-node" 2>/dev/null || true)

for pkg in "${TARGETS[@]}"; do
    install_into "$pkg/node_modules/sherpa-onnx-android-arm64"
    # Also place directly in package root as fallback
    cp -f "$WORK/sherpa-onnx.node" "$pkg/" 2>/dev/null || true
    cp -f "$WORK"/lib*.so "$pkg/" 2>/dev/null || true
done

# ── 5. Verify require() in Node ─────────────────────────────────────────────
info "Testing sherpa-onnx-node in Node.js..."
cd "$DSH_DIR"
node -e "
const sherpa = require('sherpa-onnx-node');
if (typeof sherpa.OfflineRecognizer !== 'function' || typeof sherpa.Vad !== 'function') {
  console.error('Missing expected exports in sherpa-onnx-node');
  process.exit(1);
}
console.log('    sherpa-onnx version: ' + sherpa.version);
"
ok "sherpa-onnx native speech recognition is active and ready!"
