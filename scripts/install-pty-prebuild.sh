#!/data/data/com.termux/files/usr/bin/bash
# install-pty-prebuild.sh — install the GitHub-built pty.node for this device ABI.
#
# node-pty ships no Android binary, so every `pnpm install` on Termux
# leaves the harness unable to load @deepseek-ai/dsh-subprocess-local. The
# "node-pty prebuild" workflow compiles that binary on
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
# node-pty searches prebuilds/<platform>-<arch>, so this script must place the
# binary in exactly the directory the running Node will look in. Previously
# this was the literal android-arm64, which no 32-bit device ever matched and
# which arm64 devices matched while holding a 32-bit binary.
NODE_ARCH=$(node -p 'process.arch' 2>/dev/null || echo "")
[ -n "$NODE_ARCH" ] || { echo "node is required to resolve the pty ABI" >&2; exit 1; }
PREBUILD_DIR="android-${NODE_ARCH}"
CACHE="$HOME/.dsh/native/$PREBUILD_DIR"
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
    for name in "pty-$PREBUILD_DIR" "pty-$PREBUILD_DIR-termux" "pty-$PREBUILD_DIR-ndk"; do
        if gh run download "$RUN_ID" --repo "$REPO" -n "$name" -D "$WORK/dl" 2>/dev/null; then
            ok "Fetched artifact: $name"; got=1; break
        fi
    done
    [ "$got" -eq 1 ] || { err "run $RUN_ID has no pty artifact (expired, or the build failed)"; exit 1; }
    cp "$WORK/dl/prebuilds/$PREBUILD_DIR/pty.node" "$WORK/pty.node"

    # Verify against the checksum that actually ships. Every per-ABI artifact
    # writes pty.node.sha256 at its root; manifest.json exists only in the
    # pty-android-all aggregate, which is not the artifact fetched above, so a
    # check keyed on the manifest alone never ran. Accept either, preferring
    # the per-ABI checksum, and fail loudly when a checksum is present but
    # does not match.
    HAVE=$(sha256sum "$WORK/pty.node" | cut -d' ' -f1)
    WANT=""
    if [ -f "$WORK/dl/pty.node.sha256" ]; then
        WANT=$(cut -d' ' -f1 < "$WORK/dl/pty.node.sha256")
    elif [ -f "$WORK/dl/manifest.json" ]; then
        WANT=$(node -p "require('$WORK/dl/manifest.json').sha256" 2>/dev/null || echo "")
    fi
    if [ -n "$WANT" ]; then
        [ "$WANT" = "$HAVE" ] || { err "sha256 mismatch: expected $WANT, downloaded $HAVE"; exit 1; }
        ok "sha256 verified: ${HAVE:0:16}…"
    else
        warn "artifact carried no checksum — skipping integrity verification"
    fi
    if [ -f "$WORK/dl/manifest.json" ]; then
        node -e "const m=require('$WORK/dl/manifest.json'); console.log('    node-pty '+m.node_pty_version+', built by '+m.built_by)" 2>/dev/null || true
    fi
fi

# ── 2. Assert the ELF matches this device ───────────────────────────────────
# Read the header directly: `file` is not installed by install-termux.sh, so
# matching its description silently rejected valid binaries on devices without
# it. dsh_arch owns the class/machine table.
ELF_HEX=$(od -An -tx1 -N20 "$WORK/pty.node" 2>/dev/null | tr -d ' \n')
if [ -z "$ELF_HEX" ]; then
    err "cannot read $WORK/pty.node"; exit 1
fi
if node -e '
const { execFileSync } = require("node:child_process");
const path = require("node:path");
const hex = process.argv[1];
const out = execFileSync("python3", ["-c",
  "import sys; sys.path.insert(0, sys.argv[1]); import dsh_arch; print(dsh_arch.binary_matches(bytes.fromhex(sys.argv[2]), sys.argv[3]))",
  path.dirname(process.argv[2]), hex, process.arch], { encoding: "utf8" });
process.exit(out.trim() === "True" ? 0 : 1);
' "$ELF_HEX" "$0"; then
    ok "Binary matches $PREBUILD_DIR (elf $(echo "$ELF_HEX" | cut -c7-8), machine $(echo "$ELF_HEX" | cut -c37-40))"
else
    READABLE=$(file -b "$WORK/pty.node" 2>/dev/null || echo "ELF header $ELF_HEX")
    err "binary does not match this device ($PREBUILD_DIR): $READABLE"
    err "Build the $PREBUILD_DIR artifact: .github/workflows/build-termux-pty.yml"
    exit 1
fi

# ── 3. Cache + install into every node-pty in the tree ──────────────────────
mkdir -p "$CACHE"
install -m 0644 "$WORK/pty.node" "$CACHE/pty.node"
ok "Cached → $CACHE/pty.node"

mapfile -t TARGETS < <(find "$DSH_DIR/node_modules" "$HOME/.dsh" \
    -type d -name node-pty -not -path '*/node-pty/*' 2>/dev/null || true)
[ "${#TARGETS[@]}" -gt 0 ] || { err "no node-pty package found under $DSH_DIR/node_modules"; exit 1; }

for pkg in "${TARGETS[@]}"; do
    mkdir -p "$pkg/prebuilds/$PREBUILD_DIR"
    # cp -f, never in-place edit: package files are hardlinks into the pnpm store.
    rm -f "$pkg/prebuilds/$PREBUILD_DIR/pty.node"
    install -m 0644 "$WORK/pty.node" "$pkg/prebuilds/$PREBUILD_DIR/pty.node"
    ok "Installed → ${pkg#$HOME/}/prebuilds/$PREBUILD_DIR/pty.node"
done

# ── 4. Prove the installed binary loads and can fork a pty ─────────────────
# Load the package that was actually patched: `require("node-pty")` from the
# repo root resolves through pnpm's layout and can pick a different copy (or
# none at all), which made this step fail after a successful install.
info "Load test..."
FIRST_PKG="${TARGETS[0]}"
if [ ! -f "$FIRST_PKG/lib/index.js" ]; then
    # A bare package with only a prebuilds directory (a stripped install, or a
    # fixture) has no JavaScript entry point to spawn through. The binary is
    # already placed; report that instead of failing on a missing entry file.
    warn "Skipping the fork test: $FIRST_PKG/lib/index.js is absent."
    ok "Installed $PREBUILD_DIR pty.node. Run: dsh"
    exit 0
fi
node -e '
const path = require("node:path");
const packageDir = process.argv[1];
const pty = require(path.join(packageDir, "lib", "index.js"));
const t = pty.spawn("sh", ["-c", "echo PTY_OK"], { cols: 80, rows: 24 });
let out = "";
t.onData(d => { out += d; });
t.onExit(({ exitCode }) => {
  if (!out.includes("PTY_OK")) { console.error("pty produced no output (exit " + exitCode + ")"); process.exit(1); }
  console.log("    forked a pty, child said: " + JSON.stringify(out.trim()));
  process.exit(0);
});
setTimeout(() => { console.error("pty spawn timed out"); process.exit(1); }, 15000);
' "$FIRST_PKG"
ok "node-pty works. Run: dsh"
