#!/data/data/com.termux/files/usr/bin/bash
# ==============================================================================
#  DeepSeek Harness — Automated 1-Line Termux & Mobile Installer
#  Repository: https://github.com/salmanbappi/deepseek-harness
#  Design: Option 1 (Monolith Minimalist — Black, White, and Monochrome)
# ==============================================================================
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
export NODE_OPTIONS="--max-old-space-size=2560 ${NODE_OPTIONS:-}"
export PATH="$HOME/bin:$HOME/.npm-global/bin:$PATH"
# Prevent Corepack and pnpm engine from downloading @pnpm/exe native binaries on Android
export COREPACK_ENABLE_PROJECT_SPEC=0
export COREPACK_ENABLE_STRICT=0
export COREPACK_ENABLE_AUTO_PIN=0
export pnpm_config_pm_on_fail=ignore
export pnpm_config_manage_package_manager_versions=false
corepack disable 2>/dev/null || true

# ── Monochrome Palette & Typography (Option 1) ────────────────────────────────
BOLD='\033[1m'
DIM='\033[2m'
W='\033[1;37m'          # Pure bright white
G='\033[38;5;245m'       # Medium grey
DG='\033[38;5;238m'      # Dark slate grey
LG='\033[38;5;252m'      # Light neutral grey
R='\033[7m'              # Inverse / Reverse video
N='\033[0m'              # Reset

# Responsive width formatting for mobile terminals
TERM_COLS=$(tput cols 2>/dev/null || echo 64)
[ "$TERM_COLS" -gt 64 ] && WIDTH=64 || WIDTH="$TERM_COLS"
[ "$WIDTH" -lt 45 ] && WIDTH=45
DIVIDER=$(printf '─%.0s' $(seq 1 "$WIDTH"))

# Diagnostic log buffer
TMP_DIR="${TMPDIR:-/data/data/com.termux/files/usr/tmp}"
mkdir -p "$TMP_DIR" 2>/dev/null || true
ERR_LOG=$(mktemp "${TMP_DIR}/dsh_install_err_XXXXXX.log" 2>/dev/null || echo "${TMP_DIR}/dsh_install_err.log")
trap 'rm -f "$ERR_LOG" 2>/dev/null || true' EXIT

# ── Animation & Progress Helpers ──────────────────────────────────────────────
SPIN_PID=""

start_spinner() {
    local msg="$1"
    tput civis 2>/dev/null || true
    (
        frames=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
        i=0
        while true; do
            printf "\r ${W}%s${N} ${LG}%s${N}\033[K" "${frames[$i]}" "$msg"
            i=$(( (i + 1) % 10 ))
            sleep 0.08
        done
    ) &
    SPIN_PID=$!
}

stop_spinner() {
    local status="${1:-0}"
    local label="${2:-}"
    if [ -n "$SPIN_PID" ]; then
        kill "$SPIN_PID" 2>/dev/null || true
        wait "$SPIN_PID" 2>/dev/null || true
        SPIN_PID=""
    fi
    tput cnorm 2>/dev/null || true
    if [ "$status" -eq 0 ]; then
        printf "\r ${W}●${N} %-44s ${W}[ PASS ]${N}\n" "$label"
    else
        printf "\r ${R}${W} ✕ ${N} %-44s ${R}${W}[ FAIL ]${N}\n" "$label"
    fi
}

fail_and_dump() {
    local step_name="$1"
    stop_spinner 1 "$step_name" 2>/dev/null || true
    echo -e "\n${DG}${DIVIDER}${N}"
    echo -e " ${R}${W} INSTALLATION ERROR DIAGNOSTIC DUMP ${N}"
    echo -e "${DG}${DIVIDER}${N}"
    echo -e " ${W}Stage Failed:${N} ${LG}${step_name}${N}\n"
    if [ -f "$ERR_LOG" ] && [ -s "$ERR_LOG" ]; then
        echo -e " ${G}Captured Diagnostic Output:${N}"
        sed 's/^/   /' "$ERR_LOG" | tail -n 25
    fi
    echo -e "\n${DG}${DIVIDER}${N}"
    echo -e " ${W}Installation stopped. Run 'dsh-doctor' or check the diagnostics above.${N}"
    echo -e "${DG}${DIVIDER}${N}\n"
    exit 1
}

banner() {
    echo -e "${DG}${DIVIDER}${N}"
    echo -e " ${W}DEEPSEEK HARNESS${N} ${G}— Termux & Mobile Setup${N}"
    echo -e "${DG}${DIVIDER}${N}"
}

# ── Stage 1: Pre-flight Environment & External Asset Verification ─────────────
banner
printf " ${W}◌${N} ${LG}Running pre-flight environment & resource verification...${N}"

ERRORS=()
REMEDIES=()
NOTICES=()

# 1. Termux OS Verification
if [ ! -d "/data/data/com.termux/files" ] && [ -z "${PREFIX:-}" ]; then
    ERRORS+=("Not running inside native Termux Android environment.")
    REMEDIES+=("Launch Termux on Android and run the installer from inside Termux.")
fi

# 2. Disk Storage Probe (Minimum 1,200 MB free)
FREE_KB=$(df -k "$HOME" 2>/dev/null | awk 'NR==2 {print $4}' || echo "0")
FREE_MB=$(( FREE_KB / 1024 ))
if [ "$FREE_MB" -lt 1200 ]; then
    ERRORS+=("Insufficient disk space: only ${FREE_MB} MB free (1,200 MB required).")
    REMEDIES+=("Free disk storage by running 'pkg clean' and removing old caches/files.")
fi

# 3. CPU Architecture Probe
ARCH=$(uname -m 2>/dev/null || echo "unknown")
BIT=$(getconf LONG_BIT 2>/dev/null || echo "64")
if [ "$BIT" = "32" ] || [ "$ARCH" = "armv7l" ] || [ "$ARCH" = "armv8l" ] || [ "$ARCH" = "arm" ]; then
    NOTICES+=("32-bit CPU/userspace ($ARCH / ${BIT}-bit) detected; enabling pure-JS/WASM mode.")
fi

# 4. GitHub API Reachability
GH_CODE=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 6 "https://api.github.com" 2>/dev/null || echo "000")
if [ "$GH_CODE" = "000" ]; then
    ERRORS+=("GitHub API (api.github.com) is unreachable (connection timed out).")
    REMEDIES+=("Check your device's Wi-Fi/cellular connection, DNS, or VPN settings.")
fi

# 5. Git Remote Repository Reachability
REPO_URL="https://github.com/salmanbappi/deepseek-harness.git"
REPO_CODE=$(curl -sIL -o /dev/null -w "%{http_code}" --connect-timeout 6 "$REPO_URL" 2>/dev/null || echo "000")
if [ "$REPO_CODE" = "000" ] || [ "$REPO_CODE" -ge 400 ]; then
    ERRORS+=("Git repository is unreachable at $REPO_URL (HTTP $REPO_CODE).")
    REMEDIES+=("Ensure GitHub is accessible without local proxy or firewall blocking.")
fi

# 6. Latest Release Prebuilt Tarball Probe
REPO_OWNER="salmanbappi"
REPO_NAME="deepseek-harness"
LATEST_TAG=$(curl -sI --connect-timeout 6 "https://github.com/$REPO_OWNER/$REPO_NAME/releases/latest" 2>/dev/null | grep -i "^location:" | awk '{print $2}' | tr -d '\r\n' | sed -E 's|.*/tag/||' || true)

if [ -z "$LATEST_TAG" ]; then
    LATEST_JSON=$(curl -sL --connect-timeout 6 "https://api.github.com/repos/$REPO_OWNER/$REPO_NAME/releases/latest" 2>/dev/null || true)
    LATEST_TAG=$(echo "$LATEST_JSON" | grep '"tag_name":' | head -n 1 | cut -d '"' -f 4 || true)
fi

if [ -n "$LATEST_TAG" ]; then
    TARBALL_URL="https://github.com/$REPO_OWNER/$REPO_NAME/releases/download/$LATEST_TAG/dsh-termux-prebuilt-${LATEST_TAG}.tar.gz"
    TAR_CODE=$(curl -sIL -o /dev/null -w "%{http_code}" --connect-timeout 6 "$TARBALL_URL" 2>/dev/null || echo "000")
    if [ "$TAR_CODE" != "200" ] && [ "$TAR_CODE" != "302" ]; then
        NOTICES+=("Release $LATEST_TAG tarball returned HTTP $TAR_CODE; local fallback will engage.")
    fi
else
    NOTICES+=("Could not query GitHub releases API; repository git sync will proceed directly.")
fi

# Pre-flight Abort Gate
if [ "${#ERRORS[@]}" -gt 0 ]; then
    printf "\r ${R}${W} ✕ ${N} %-44s ${R}${W}[ FAIL ]${N}\n" "Pre-flight Environment & External Assets"
    echo -e "\n${DG}${DIVIDER}${N}"
    echo -e " ${R}${W} PRE-FLIGHT DIAGNOSTICS & ABORT DUMP ${N}"
    echo -e "${DG}${DIVIDER}${N}"
    echo -e " ${W}Pre-flight verification detected ${#ERRORS[@]} blocking issue(s):${N}\n"
    for i in "${!ERRORS[@]}"; do
        idx=$(( i + 1 ))
        echo -e "  ${W}[0${idx}] ERROR:${N}   ${LG}${ERRORS[$i]}${N}"
        echo -e "       ${G}Remedy:${N}  ${G}${REMEDIES[$i]}${N}\n"
    done
    echo -e "${DG}${DIVIDER}${N}"
    echo -e " ${W}No files or repositories were modified. Setup aborted safely.${N}"
    echo -e "${DG}${DIVIDER}${N}\n"
    exit 1
fi

printf "\r ${W}●${N} %-44s ${W}[ PASS ]${N}\n" "Pre-flight Environment & External Assets"
for notice in "${NOTICES[@]}"; do
    echo -e "   ${DG}↳ ${G}${notice}${N}"
done

# ── Stage 2: Minimal System Toolchain Check & Installation ─────────────────────
start_spinner "Checking and installing minimal system packages..."
PACKAGES="nodejs-lts python git tar curl"
MISSING_PKGS=""
for pkg in $PACKAGES; do
    if ! command -v "$pkg" &>/dev/null && ! dpkg -s "$pkg" &>/dev/null; then
        MISSING_PKGS="$MISSING_PKGS $pkg"
    fi
done

if [ -n "$MISSING_PKGS" ]; then
    pkg update -y >"$ERR_LOG" 2>&1 || true
    pkg install -y -o Dpkg::Options::="--force-confold" $MISSING_PKGS >"$ERR_LOG" 2>&1 || \
        apt-get install -y $MISSING_PKGS >"$ERR_LOG" 2>&1 || fail_and_dump "System packages ($MISSING_PKGS)"
    pkg clean 2>/dev/null || true
fi

# Ensure pnpm is available (Termux pkg or npm fallback, never @pnpm/exe)
if ! command -v pnpm &>/dev/null; then
    apt-get install --reinstall -y pnpm >"$ERR_LOG" 2>&1 || \
        pkg install -y -o Dpkg::Options::="--force-confold" pnpm >"$ERR_LOG" 2>&1 || \
        npm install -g pnpm@9 >"$ERR_LOG" 2>&1 || \
        npm install -g pnpm >"$ERR_LOG" 2>&1 || true
    hash -r 2>/dev/null || true
fi

if ! command -v pnpm &>/dev/null; then
    echo "pnpm command not found after installation attempt" >"$ERR_LOG"
    fail_and_dump "Package Manager Setup (pnpm)"
fi
stop_spinner 0 "Minimal System Toolchain (Node, Python, Git)"

# ── Stage 3: DeepSeek Harness Repository Workspace Sync ────────────────────────
DSH_DIR="$HOME/deepseek-harness"
start_spinner "Synchronizing repository workspace..."
git config --global --add safe.directory "$DSH_DIR" 2>/dev/null || true

if [ -d "$DSH_DIR/.git" ]; then
    cd "$DSH_DIR"
    git fetch origin master --quiet >"$ERR_LOG" 2>&1 || true
    git checkout master --quiet >"$ERR_LOG" 2>&1 || true
    git pull origin master --quiet >"$ERR_LOG" 2>&1 || fail_and_dump "Repository Update (git pull)"
else
    MAX_RETRIES=3
    COUNT=0
    CLONED=0
    until [ "$COUNT" -ge "$MAX_RETRIES" ]; do
        if git clone --depth=1 https://github.com/salmanbappi/deepseek-harness.git "$DSH_DIR" >"$ERR_LOG" 2>&1; then
            CLONED=1
            break
        fi
        COUNT=$((COUNT+1))
        sleep 2
    done
    if [ "$CLONED" -eq 0 ]; then
        fail_and_dump "Repository Clone (git clone)"
    fi
    cd "$DSH_DIR"
fi
stop_spinner 0 "DeepSeek Harness Workspace Sync"

# ── Stage 4: Deploy Pre-compiled Cloud Release Artifacts ──────────────────────
start_spinner "Resolving cloud prebuilt binary bundle..."
cd "$DSH_DIR"
DOWNLOAD_SUCCESS=0

# Check existing valid build
if [ -f "apps/cli/lib/bin.js" ] && [ -d "apps/web/dist" ] && [ -f "packages/client/ui-chat/lib/client.js" ]; then
    DOWNLOAD_SUCCESS=1
    stop_spinner 0 "Deploy Cloud Prebuilt Binaries (Verified)"
else
    if [ -n "$LATEST_TAG" ]; then
        stop_spinner 0 "Deploy Cloud Prebuilt Binaries ($LATEST_TAG)"
        TARBALL_URL="https://github.com/$REPO_OWNER/$REPO_NAME/releases/download/$LATEST_TAG/dsh-termux-prebuilt-${LATEST_TAG}.tar.gz"
        DEST_TAR="$DSH_DIR/prebuilt.tar.gz"

        # Download with clean monochrome progress bar
        python3 -c "
import urllib.request, sys, time, os

url = '$TARBALL_URL'
dest = '$DEST_TAR'

req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        total = int(resp.headers.get('content-length', 0))
        downloaded = 0
        chunk_size = 131072
        start_time = time.time()
        with open(dest, 'wb') as f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                pct = int(downloaded * 100 / total) if total > 0 else 0
                width = 24
                filled = int(pct * width / 100)
                bar = '█' * filled + '░' * (width - filled)
                cur_mb = downloaded / (1024 * 1024)
                tot_mb = total / (1024 * 1024)
                speed = cur_mb / max(0.1, time.time() - start_time)
                sys.stdout.write(f'\r   \033[1;37m[{bar}]\033[0m \033[1;37m{pct}%\033[0m  \033[38;5;244m{cur_mb:.1f} MB / {tot_mb:.1f} MB ({speed:.1f} MB/s)\033[0m\033[K')
                sys.stdout.flush()
    print()
except Exception as e:
    sys.exit(1)
" >"$ERR_LOG" 2>&1 || true

        if [ -f "$DEST_TAR" ] && [ -s "$DEST_TAR" ]; then
            tar -xzf "$DEST_TAR" -C "$DSH_DIR" >"$ERR_LOG" 2>&1 || true
            rm -f "$DEST_TAR"
            if [ -f "apps/cli/lib/bin.js" ] && [ -d "apps/web/dist" ]; then
                DOWNLOAD_SUCCESS=1
            fi
        fi
    fi

    if [ "$DOWNLOAD_SUCCESS" -eq 0 ]; then
        start_spinner "Compiling packages locally with memory ceiling..."
        pnpm run build:lib:host >"$ERR_LOG" 2>&1 || true
        pnpm run build:lib:client >"$ERR_LOG" 2>&1 || true
        pnpm run build:web >"$ERR_LOG" 2>&1 || true
        stop_spinner 0 "Deploy Cloud Prebuilt Binaries (Local Compile)"
    fi
fi

# ── Stage 5: Termux Mobile UX Suite & Dependency Linking ──────────────────────
start_spinner "Applying mobile patches and linking production dependencies..."
cd "$DSH_DIR"

# Global CLI launcher commands (~/bin)
BIN_DIR="$HOME/bin"
mkdir -p "$BIN_DIR"

cat <<'LAUNCHER_EOF' > "$BIN_DIR/dsh"
#!/data/data/com.termux/files/usr/bin/bash
set -e
export COREPACK_ENABLE_PROJECT_SPEC=0
export COREPACK_ENABLE_STRICT=0
export COREPACK_ENABLE_AUTO_PIN=0
export pnpm_config_pm_on_fail=ignore
export pnpm_config_manage_package_manager_versions=false
export NODE_OPTIONS="--max-old-space-size=2560 ${NODE_OPTIONS:-}"
DSH_DIR="$HOME/deepseek-harness"

if [ ! -d "$DSH_DIR" ]; then
    echo "[!] Error: DeepSeek Harness directory not found at $DSH_DIR" >&2
    exit 1
fi

if [ -f "$DSH_DIR/apps/cli/lib/bin.js" ]; then
    exec node --expose-internals "$DSH_DIR/apps/cli/lib/bin.js" "$@"
else
    exec node --expose-internals --import "$DSH_DIR/node_modules/tsx/dist/esm/index.mjs" "$DSH_DIR/apps/cli/src/bin.ts" "$@"
fi
LAUNCHER_EOF
chmod +x "$BIN_DIR/dsh"

if [ -f "$DSH_DIR/scripts/dsh-update.sh" ]; then
    cp -f "$DSH_DIR/scripts/dsh-update.sh" "$BIN_DIR/dsh-update"
fi
chmod +x "$BIN_DIR/dsh-update" 2>/dev/null || true

cat <<'DOCTOR_EOF' > "$BIN_DIR/dsh-doctor"
#!/data/data/com.termux/files/usr/bin/bash
set -e
DSH_DIR="$HOME/deepseek-harness"
echo "──────────────────────────────────────────"
echo "      DeepSeek Harness Termux Doctor      "
echo "──────────────────────────────────────────"
echo "[*] Node.js:           $(node -v 2>/dev/null || echo 'FAIL')"
echo "[*] pnpm:              $(pnpm -v 2>/dev/null || echo 'FAIL')"
echo "[*] Python3:           $(python3 --version 2>/dev/null || echo 'FAIL')"
echo "[*] Workspace:         $DSH_DIR"
if [ -d "$DSH_DIR" ]; then
    cd "$DSH_DIR"
    python3 scripts/patch_termux.py --check || true
    echo ""
    echo "[*] Native Addons & Plugins:"
    node -e "try { require('sharp'); console.log('    - sharp (raster images):   OK'); } catch(e) { console.log('    - sharp: FAIL (' + e.message + ')'); }" 2>/dev/null || true
    node -e "try { require('node-pty'); console.log('    - node-pty (terminal):     OK'); } catch(e) { console.log('    - node-pty: FAIL (' + e.message + ')'); }" 2>/dev/null || true
    echo ""
    echo "[*] CLI Invocation Check:"
    if dsh --version >/dev/null 2>&1; then
        echo "    SUCCESS -> Version $(dsh --version 2>/dev/null)"
    else
        echo "    FAILED -> dsh failed to start"
    fi
fi
echo "──────────────────────────────────────────"
DOCTOR_EOF
chmod +x "$BIN_DIR/dsh-doctor"

cat <<'PATCH_EOF' > "$BIN_DIR/dsh-patch"
#!/data/data/com.termux/files/usr/bin/bash
set -e
DSH_DIR="$HOME/deepseek-harness"
if [ ! -d "$DSH_DIR" ]; then
    echo "[!] Error: Harness directory not found at $DSH_DIR" >&2
    exit 1
fi
cd "$DSH_DIR"
python3 "$DSH_DIR/scripts/patch_termux.py" "$@"
PATCH_EOF
chmod +x "$BIN_DIR/dsh-patch"

# Ensure PATH has ~/bin in shell rc profiles
for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile" "$HOME/.bash_profile"; do
    if [ -f "$rc" ]; then
        if ! grep -q 'HOME/bin' "$rc"; then
            echo 'export PATH="$HOME/bin:$PATH"' >> "$rc"
        fi
    else
        echo 'export PATH="$HOME/bin:$PATH"' > "$rc"
    fi
done
export PATH="$HOME/bin:$PATH"

# Apply mobile patches
python3 scripts/patch_termux.py --apply >"$ERR_LOG" 2>&1 || true

# Production-only dependency install saves 2-3 GB of devDependencies
COREPACK_ENABLE_PROJECT_SPEC=0 COREPACK_ENABLE_STRICT=0 CI=true pnpm install --prod --frozen-lockfile=false --ignore-scripts >"$ERR_LOG" 2>&1 || \
    COREPACK_ENABLE_PROJECT_SPEC=0 COREPACK_ENABLE_STRICT=0 npm install --omit=dev --ignore-scripts >"$ERR_LOG" 2>&1 || true

COREPACK_ENABLE_PROJECT_SPEC=0 COREPACK_ENABLE_STRICT=0 pnpm add -w @img/sharp-wasm32 --ignore-scripts >"$ERR_LOG" 2>&1 || true

# Prune unneeded package caches
pnpm store prune 2>/dev/null || true
pkg clean 2>/dev/null || true

python3 scripts/patch_termux.py --apply >"$ERR_LOG" 2>&1 || fail_and_dump "Termux Mobile Environment Suite"

stop_spinner 0 "Termux Mobile UX Suite & Dependency Linking"

# ── Setup Complete Banner ─────────────────────────────────────────────────────
echo -e "${DG}${DIVIDER}${N}"
echo -e " ${W}DEEPSEEK HARNESS — SETUP COMPLETE${N}"
echo -e "${DG}${DIVIDER}${N}"
echo -e " ${W}[✓] DeepSeek Harness successfully installed on Termux!${N}\n"
echo -e " ${W}Commands Available:${N}"
echo -e "   ${W}dsh web${N}        ${G}Start the Mobile Web UI (http://127.0.0.1:3080)${N}"
echo -e "   ${W}dsh-update${N}     ${G}Zero-loss upstream updater${N}"
echo -e "   ${W}dsh-doctor${N}     ${G}Verify environment & patch integrity${N}\n"
echo -e " ${W}To start right now:${N}"
echo -e "   ${W}dsh web${N}"
echo -e "${DG}${DIVIDER}${N}\n"
