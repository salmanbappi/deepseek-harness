#!/data/data/com.termux/files/usr/bin/bash
# install-pty-prebuild.sh — install the GitHub-built android-arm64 pty.node.
#
# node-pty ships no android-arm64 binary, so every `pnpm install` on Termux
# leaves the harness unable to load @deepseek-ai/dsh-subprocess-local. The
# "node-pty prebuild (Termux android-arm64)" workflow compiles that binary on
# GitHub Actions; this script fetches it, installs it into every node-pty copy
# in the tree, and caches it at ~/.dsh/native so patch_termux.py can restore it
# after future updates without another download.
#
# Usage:
#   bash scripts/install-pty-prebuild.sh                # latest successful run
#   bash scripts/install-pty-prebuild.sh --run-id 12345 # a specific run
#   bash scripts/install-pty-prebuild.sh --file pty.node # a local binary
set -euo pipefail

REPO="${DSH_REPO:-salmanbappi/deepseek-harness}"
WORKFLOW="${DSH_PTY_WORKFLOW:-build-termux-pty.yml}"
DSH_DIR="${DSH_DIR:-$HOME/deepseek-harness}"
CACHE="$HOME/.dsh/native/android-arm64"
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
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        *) err "unknown argument: $1"; exit 2 ;;
    esac
done

WORK=$(mktemp -d "${TMPDIR:-/data/data/com.termux/files/usr/tmp}/pty-prebuild.XXXXXX")
trap 'rm -rf "$WORK"' EXIT

# ── 1. Obtain the binary ────────────────────────────────────────────────────
if [ -n "$LOCAL_FILE" ]; then
    cp "$LOCAL_FILE" "$WORK/pty.node"
    info "Using local binary: $LOCAL_FILE"
else
    command -v gh >/dev/null || { err "'gh' is required (pkg install gh)"; exit 1; }
    if [ -z "$RUN_ID" ]; then
        info "Looking up the latest successful $WORKFLOW run in $REPO..."
        RUN_ID=$(gh run list --repo "$REPO" --workflow "$WORKFLOW" \
            --status success --limit 1 --json databaseId -q '.[0].databaseId' 2>/dev/null || true)
        [ -n "$RUN_ID" ] || { err "no successful $WORKFLOW run found — push the workflow and let it build first"; exit 1; }
    fi
    info "Downloading artifact from run $RUN_ID..."
    got=0
    for name in pty-android-arm64 pty-android-arm64-termux pty-android-arm64-ndk; do
        if gh run download "$RUN_ID" --repo "$REPO" -n "$name" -D "$WORK/dl" 2>/dev/null; then
            ok "Fetched artifact: $name"; got=1; break
        fi
    done
    [ "$got" -eq 1 ] || { err "run $RUN_ID has no pty artifact (expired, or the build failed)"; exit 1; }
    cp "$WORK/dl/prebuilds/android-arm64/pty.node" "$WORK/pty.node"
    if [ -f "$WORK/dl/manifest.json" ]; then
        WANT=$(node -p "require('$WORK/dl/manifest.json').sha256" 2>/dev/null || echo "")
        HAVE=$(sha256sum "$WORK/pty.node" | cut -d' ' -f1)
        if [ -n "$WANT" ] && [ "$WANT" != "$HAVE" ]; then
            err "sha256 mismatch: manifest $WANT, download $HAVE"; exit 1
        fi
        ok "sha256 verified: ${HAVE:0:16}…"
        node -e "const m=require('$WORK/dl/manifest.json'); console.log('    node-pty '+m.node_pty_version+', built by '+m.built_by)" 2>/dev/null || true
    fi
fi

# ── 2. Sanity-check the ELF ─────────────────────────────────────────────────
DESC=$(file -b "$WORK/pty.node" 2>/dev/null || echo unknown)
case "$DESC" in
    *"ELF 64-bit"*"ARM aarch64"*) ok "Binary looks right: $DESC" ;;
    *) err "not an aarch64 shared object: $DESC"; exit 1 ;;
esac

# ── 3. Cache + install into every node-pty in the tree ──────────────────────
mkdir -p "$CACHE"
install -m 0644 "$WORK/pty.node" "$CACHE/pty.node"
ok "Cached → $CACHE/pty.node"

mapfile -t TARGETS < <(find "$DSH_DIR/node_modules" "$HOME/.dsh" \
    -type d -name node-pty -not -path '*/node-pty/*' 2>/dev/null || true)
[ "${#TARGETS[@]}" -gt 0 ] || { err "no node-pty package found under $DSH_DIR/node_modules"; exit 1; }

for pkg in "${TARGETS[@]}"; do
    mkdir -p "$pkg/prebuilds/android-arm64"
    # cp -f, never in-place edit: package files are hardlinks into the pnpm store.
    rm -f "$pkg/prebuilds/android-arm64/pty.node"
    install -m 0644 "$WORK/pty.node" "$pkg/prebuilds/android-arm64/pty.node"
    ok "Installed → ${pkg#$HOME/}/prebuilds/android-arm64/pty.node"
done

# ── 4. Prove it loads and can fork a pty ────────────────────────────────────
info "Load test..."
cd "$DSH_DIR"
node -e '
const pty = require("node-pty");
const t = pty.spawn("sh", ["-c", "echo PTY_OK"], { cols: 80, rows: 24 });
let out = "";
t.onData(d => { out += d; });
t.onExit(({ exitCode }) => {
  if (!out.includes("PTY_OK")) { console.error("pty produced no output (exit " + exitCode + ")"); process.exit(1); }
  console.log("    forked a pty, child said: " + JSON.stringify(out.trim()));
  process.exit(0);
});
setTimeout(() => { console.error("pty spawn timed out"); process.exit(1); }, 15000);
'
ok "node-pty works. Run: dsh-web"
